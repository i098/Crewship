import configparser
import importlib.util
import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pool_script = load("ci_pool", "blueprint/maintenance/ci-pool.py")
REAL_DRIFTED = pool_script.drifted  # the slots fixture stubs it; drift tests restore it
ship = load("ship_config_ci_pool", "scripts/ship.py")

POOL = {"job_cpus": 4, "job_memory_gb": 8}


@pytest.mark.parametrize(
    ("event", "allowed"),
    [
        ({"ref": "refs/heads/main"}, True),
        ({"pull_request": {"head": {"repo": {"full_name": "o/repo"}}}}, True),
        ({"pull_request": {"head": {"repo": {"full_name": "outsider/repo"}}}}, False),
        ({"pull_request": {"head": {"repo": None}}}, False),
        ({"workflow_run": {"head_repository": {"full_name": "outsider/repo"}}}, False),
    ],
)
def test_job_started_hook_kills_the_container_for_code_from_outside_the_repository(
    tmp_path, event, allowed
):
    hook = tmp_path / "job-started.sh"
    hook.write_text(pool_script.HOOK_TEXT)
    (tmp_path / "event.json").write_text(json.dumps(event))
    (tmp_path / "bin").mkdir()
    sudo = tmp_path / "bin" / "sudo"
    sudo.write_text(f'#!/bin/sh\necho "$@" > {tmp_path / "sudo-args"}\n')
    sudo.chmod(0o755)
    result = subprocess.run(
        ["bash", str(hook)], capture_output=True, text=True,
        env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "GITHUB_REPOSITORY": "o/repo",
             "GITHUB_EVENT_PATH": str(tmp_path / "event.json")},
    )
    assert (result.returncode == 0) is allowed, result.stderr
    assert ("refused" in result.stderr) is not allowed
    killed = (tmp_path / "sudo-args").exists()
    assert killed is not allowed
    if killed:
        assert (tmp_path / "sudo-args").read_text().split() == ["kill", "-KILL", "-1"]


def test_auto_size_takes_half_the_host_cpus_or_memory_whichever_is_tighter():
    # 96 CPUs / 2 / 4 = 12; 247 GiB / 2 / 8 = 15.4.
    assert pool_script.auto_slots(POOL, 96, 247.0) == 12
    # Memory binds: 40 GiB / 2 / 8 = 2.5.
    assert pool_script.auto_slots(POOL, 96, 40.0) == 2


def test_slots_past_the_pool_total_are_dropped_from_the_end_of_the_list(capsys):
    pool = {"repos": [{"repo": "o/First", "slots": 2}, {"repo": "o/second.repo", "slots": 2}]}
    assert pool_script.wanted_slots(pool, 3) == ["o-first-1", "o-first-2", "o-second-repo-1"]
    assert "o-second-repo-2" in capsys.readouterr().err
    assert pool_script.wanted_slots(pool, 10) == [
        "o-first-1", "o-first-2", "o-second-repo-1", "o-second-repo-2"
    ]


@pytest.fixture
def slots(tmp_path, monkeypatch):
    """Pool state: kept-1 and gone-1 enabled, work/cache dirs for both, a foreign dir."""
    units = tmp_path / "units"
    wants = units / "default.target.wants"
    wants.mkdir(parents=True)
    (units / "ci-runner@.service").write_text(pool_script.UNIT_TEXT)
    for name in ("o-kept-1", "o-gone-1"):
        (wants / f"ci-runner@{name}.service").touch()
    data = tmp_path / "data"
    for path in ("ci-pool/work/o-kept-1", "ci-pool/work/o-gone-1", "ci-pool/apt/o-kept-1",
                 "ci-pool/apt/o-gone-1", "ci-pool/scratch/o-gone-1", "ci-pool/dind/o-gone-1",
                 "ci-pool/dind/o-kept-1", "ci-pool/cache/o-kept",
                 "ci-pool/cache/o-gone", "work/projects", "cache/models"):
        (data / path).mkdir(parents=True)
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "TEMPLATE", units / "ci-runner@.service")
    monkeypatch.setattr(pool_script, "WANTS", wants)
    monkeypatch.setattr(pool_script, "HOOK", tmp_path / "job-started.sh")
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "github_runners",
                        lambda repo: {f"o-kept-{n}": {"busy": False} for n in (1, 2)})
    monkeypatch.setattr(pool_script, "drifted", lambda names, nice: set())
    monkeypatch.setattr(pool_script, "remove_tree", shutil.rmtree)
    for attr, text in (("WATCH_SERVICE", pool_script.WATCH_SERVICE_TEXT),
                       ("WATCH_TIMER", pool_script.WATCH_TIMER_TEXT),
                       ("IMAGE_SERVICE", pool_script.IMAGE_SERVICE_TEXT),
                       ("IMAGE_TIMER", pool_script.IMAGE_TIMER_TEXT)):
        monkeypatch.setattr(pool_script, attr, units / getattr(pool_script, attr).name)
        getattr(pool_script, attr).write_text(text)
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0)  # the timers are enabled
    calls = []
    monkeypatch.setattr(pool_script, "systemctl", lambda *args: calls.append(args))

    def apply(check=False, **overrides):
        config = {"data_dir": str(data), "total_slots": 5,
                  "repos": [{"repo": "o/kept", "slots": 2, "labels": ["x"]}], **overrides}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(config)))
        return pool_script.apply(check=check)

    return data, calls, apply


def test_check_lists_removed_slots_and_their_directories_without_touching_them(
    slots, tmp_path, capsys
):
    data, calls, apply = slots

    assert apply(check=True) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"write {tmp_path / 'pool.json'}",
        f"write {tmp_path / 'job-started.sh'}",
        "stop ci-runner@o-gone-1.service",
        f"remove {data / 'ci-pool/work/o-gone-1'}",
        f"remove {data / 'ci-pool/scratch/o-gone-1'}",
        f"remove {data / 'ci-pool/apt/o-gone-1'}",
        f"remove {data / 'ci-pool/dind/o-gone-1'}",
        f"remove {data / 'ci-pool/cache/o-gone'}",
        "restart ci-runner@o-kept-1.service",
        "start ci-runner@o-kept-2.service",
    ]
    assert not (tmp_path / "pool.json").exists()
    assert (data / "ci-pool/work/o-gone-1").is_dir()
    assert calls == []


def test_apply_deletes_only_what_the_pool_created(slots):
    data, calls, apply = slots

    assert apply() == 0

    assert not (data / "ci-pool/work/o-gone-1").exists()
    assert not (data / "ci-pool/scratch/o-gone-1").exists()
    assert not (data / "ci-pool/apt/o-gone-1").exists()
    assert not (data / "ci-pool/dind/o-gone-1").exists()
    assert (data / "ci-pool/dind/o-kept-1").is_dir()
    assert not (data / "ci-pool/cache/o-gone").exists()
    assert (data / "ci-pool/work/o-kept-1").is_dir()
    assert (data / "ci-pool/apt/o-kept-1").is_dir()
    assert (data / "work/projects").is_dir()
    assert (data / "cache/models").is_dir()
    assert ("disable", "--now", "ci-runner@o-gone-1.service") in calls


def test_shrinking_stops_idle_slots_but_only_drains_busy_ones(slots, monkeypatch, capsys):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-kept-2")
    (data / "ci-pool/work/o-kept-2").mkdir()
    (pool_script.WANTS / "ci-runner@o-kept-2.service").touch()

    assert apply(total_slots=1) == 0

    assert ("disable", "ci-runner@o-kept-2.service") in calls
    assert ("disable", "--now", "ci-runner@o-kept-2.service") not in calls
    assert ("disable", "--now", "ci-runner@o-gone-1.service") in calls
    assert (data / "ci-pool/work/o-kept-2").is_dir()
    assert (data / "ci-pool/cache/o-kept").is_dir()
    assert not (data / "ci-pool/work/o-gone-1").exists()
    assert "drain ci-runner@o-kept-2.service" in capsys.readouterr().out


def test_busy_reads_docker_top_output_with_a_pid_column(monkeypatch):
    tops = {
        "ci-runner-idle": "PID  COMM\n1  run.sh\n20  Runner.Listener\n",
        "ci-runner-busy": "PID  COMM\n1  run.sh\n20  Runner.Listener\n31  Runner.Worker\n",
    }

    def fake_run(argv, **kwargs):
        # Docker rejects `top -eo comm`: it needs a pid field.
        listing = tops.get(argv[-3])
        ok = listing is not None and "pid" in argv[-1]
        return subprocess.CompletedProcess(
            argv, 0 if ok else 1, listing if ok else "",
            "" if ok else "Couldn't find PID field in ps output" if listing else
            "container abc is not running" if argv[-3] == "ci-runner-created" else "No such container",
        )

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    assert not pool_script.busy("idle")
    assert pool_script.busy("busy")
    assert not pool_script.busy("missing")
    assert not pool_script.busy("created")  # created, never started: no job


def test_a_drained_slot_keeps_its_repository_cache_while_it_is_busy(slots, monkeypatch):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-gone-1")

    assert apply(repos=[]) == 0

    assert (data / "ci-pool/work/o-gone-1").is_dir()
    assert (data / "ci-pool/scratch/o-gone-1").is_dir()
    assert (data / "ci-pool/apt/o-gone-1").is_dir()
    assert (data / "ci-pool/cache/o-gone").is_dir()
    assert not (data / "ci-pool/work/o-kept-1").exists()
    assert not (data / "ci-pool/apt/o-kept-1").exists()
    assert not (data / "ci-pool/cache/o-kept").exists()


def test_auto_size_comes_from_host_totals_whatever_the_slots_are_doing(slots, monkeypatch, capsys):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: True)
    monkeypatch.setattr(pool_script, "totals", lambda: (96, 247.0))

    assert apply(total_slots="auto", repos=[{"repo": "o/kept", "slots": 20, "labels": ["x"]}]) == 0

    assert "pool: 12 of 12 slots" in capsys.readouterr().err


def test_a_config_change_restarts_idle_slots_and_leaves_busy_ones(slots, monkeypatch, capsys):
    data, calls, apply = slots
    assert apply() == 0
    calls.clear()
    capsys.readouterr()

    assert apply() == 0
    assert not [call for call in calls if call[0] == "restart"]

    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-kept-1")
    assert apply(repos=[{"repo": "o/kept", "slots": 2, "labels": ["y"]}]) == 0

    assert [call for call in calls if call[0] == "restart"] == []
    assert "start ci-runner@o-kept-2.service" in capsys.readouterr().out

    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    assert apply(repos=[{"repo": "o/kept", "slots": 2, "labels": ["z"]}]) == 0

    assert ("restart", "ci-runner@o-kept-1.service") in calls
    assert "restart ci-runner@o-kept-1.service" in capsys.readouterr().out


@pytest.mark.parametrize("listed", [
    {"o-kept-1": {"busy": True}},  # GitHub gave the runner a job; its worker has not started
    {},  # the GitHub read failed or does not list the runner
])
def test_a_config_change_restarts_no_slot_that_github_does_not_show_idle(slots, monkeypatch, listed):
    data, calls, apply = slots
    assert apply() == 0
    calls.clear()
    monkeypatch.setattr(pool_script, "github_runners", lambda repo: listed)

    assert apply(repos=[{"repo": "o/kept", "slots": 2, "labels": ["y"]}]) == 0

    assert ("restart", "ci-runner@o-kept-1.service") not in calls
    assert json.loads(pool_script.CONFIG.read_text())["repos"][0]["labels"] == ["y"]


@pytest.fixture
def ci_slice(monkeypatch):
    """The system manager's ci.slice as `systemctl show` and `sudo -n systemctl set-property` see it,
    and each job container's cgroup parent as `docker inspect` shows it (`parents`; None fails the read)."""
    state = {"weight": "[not set]", "refuse": False, "sets": 0, "parents": {}}
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])

    def fake_run(argv, **kwargs):
        if argv[:2] == ["sudo", "-n"]:
            assert argv[2:5] == ["systemctl", "set-property", "ci.slice"]
            if state["refuse"]:
                return subprocess.CompletedProcess(argv, 1)
            state["weight"], state["sets"] = argv[5].removeprefix("CPUWeight="), state["sets"] + 1
            return subprocess.CompletedProcess(argv, 0)
        if "inspect" in argv:
            if state["parents"] is None:
                return subprocess.CompletedProcess(argv, 124, "", "")
            names = argv[argv.index("--format") + 2:]
            shown = [f"/{name} {state['parents'][name]}" for name in names if name in state["parents"]]
            return subprocess.CompletedProcess(argv, int(len(shown) < len(names)), "\n".join(shown) + "\n", "")
        assert "show" in argv and "ci.slice" in argv
        return subprocess.CompletedProcess(argv, 0, state["weight"] + "\n", "")

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    return state


def restarts(calls):
    return [call[1] for call in calls if call[0] == "restart"]


def test_a_slot_skipped_while_github_was_unreadable_is_restarted_by_the_next_apply(slots, ci_slice, monkeypatch):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "drifted", REAL_DRIFTED)
    ci_slice["parents"] = {"ci-runner-o-kept-1": ""}  # started before `nice`: in system.slice
    assert apply() == 0
    calls.clear()

    monkeypatch.setattr(pool_script, "github_runners", lambda repo: {})
    assert apply(nice=10) == 0
    assert restarts(calls) == []

    monkeypatch.setattr(pool_script, "github_runners", lambda repo: {"o-kept-1": {"busy": False}})
    assert apply(nice=10) == 0
    assert restarts(calls) == ["ci-runner@o-kept-1.service"]

    calls.clear()
    ci_slice["parents"] = {"ci-runner-o-kept-1": "ci.slice"}  # the restarted slot's new container
    assert apply(nice=10) == 0
    assert restarts(calls) == []


@pytest.mark.parametrize("hold", ["github busy", "worker running", "inspect failed", "no container"])
def test_a_later_apply_never_restarts_a_busy_or_unknown_slot(slots, ci_slice, monkeypatch, hold):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "drifted", REAL_DRIFTED)
    ci_slice["parents"] = {"ci-runner-o-kept-1": ""}
    assert apply(nice=10) == 0  # writes pool.json; later applies see no config change
    calls.clear()
    if hold == "github busy":
        monkeypatch.setattr(pool_script, "github_runners", lambda repo: {"o-kept-1": {"busy": True}})
    elif hold == "worker running":
        monkeypatch.setattr(pool_script, "busy", lambda name: True)
    elif hold == "inspect failed":
        ci_slice["parents"] = None
    else:
        ci_slice["parents"] = {}

    for _ in range(2):
        assert apply(nice=10) == 0
    assert restarts(calls) == []


def test_nice_lowers_the_ci_slice_weight_once_and_gives_the_slots_that_nice(slots, ci_slice, capsys):
    data, calls, apply = slots
    assert apply() == 0
    assert ci_slice["sets"] == 0 and "Nice=" not in pool_script.TEMPLATE.read_text()
    capsys.readouterr()

    assert apply(check=True, nice=10) == 0
    assert ci_slice["weight"] == "[not set]"
    assert "set ci.slice CPUWeight=11" in capsys.readouterr().out

    assert apply(nice=10) == 0
    assert ci_slice["weight"] == "11"
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.read_string(pool_script.TEMPLATE.read_text())
    # systemd merges a repeated [Service] section the same way.
    assert unit["Service"]["Nice"] == "10" and unit["Service"]["Restart"] == "always"
    assert ("daemon-reload",) in calls
    capsys.readouterr()

    assert apply(nice=10) == 0
    assert ci_slice["sets"] == 1
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith(("set", "write"))]


def test_a_refused_slice_weight_leaves_the_pool_unchanged(slots, ci_slice, tmp_path):
    data, calls, apply = slots
    ci_slice["refuse"] = True

    with pytest.raises(SystemExit, match=r"ci\.slice.*exited 1"):
        apply(nice=10)

    assert not (tmp_path / "pool.json").exists()
    assert calls == []
    assert "Nice=" not in pool_script.TEMPLATE.read_text()
    ci_slice["refuse"] = False
    assert apply(nice=10) == 0
    assert ci_slice["weight"] == "11"


@pytest.mark.parametrize("nice, valid", [(0, True), (19, True), (-1, False), (20, False), (1.5, False)])
def test_nice_only_lowers_the_priority(configuration, nice, valid):
    configuration["crewship"]["ci_pool"]["nice"] = nice
    if valid:
        ship.validate_config(configuration)
    else:
        with pytest.raises(Exception, match="nice"):
            ship.validate_config(configuration)


def test_a_failed_apply_keeps_the_old_config_so_the_rerun_restarts_idle_slots(slots, monkeypatch):
    data, calls, apply = slots
    repos = [{"repo": "o/kept", "slots": 2, "labels": ["y"]}]

    def fail(path):
        raise subprocess.CalledProcessError(1, "docker")

    monkeypatch.setattr(pool_script, "remove_tree", fail)
    with pytest.raises(subprocess.CalledProcessError):
        apply(repos=repos)
    assert not pool_script.CONFIG.exists()

    monkeypatch.setattr(pool_script, "remove_tree", shutil.rmtree)
    assert apply(repos=repos) == 0

    assert ("restart", "ci-runner@o-kept-1.service") in calls
    assert json.loads(pool_script.CONFIG.read_text())["repos"] == repos


@pytest.fixture
def configuration():
    document = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    document["crewship"]["profiles"]["docker"] = True
    document["crewship"]["ci_pool"] = {
        "data_dir": "/srv/ci",
        "repos": [{"repo": "o/repo", "slots": 2, "labels": ["pool"]}],
    }
    return document


def test_two_repositories_that_share_a_unit_name_are_rejected(configuration):
    configuration["crewship"]["ci_pool"]["repos"].append(
        {"repo": "O/Repo", "slots": 1, "labels": ["pool"]}
    )
    with pytest.raises(ValueError, match="twice"):
        ship.validate_config(configuration)


def test_pool_requires_the_docker_profile(configuration):
    configuration["crewship"]["profiles"]["docker"] = False
    configuration["crewship"]["profiles"]["fleet_guards"] = False
    with pytest.raises(ValueError, match="docker profile"):
        ship.validate_config(configuration)


def test_failed_container_create_deletes_the_runner_and_pauses(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"), "job_cpus": 4, "job_memory_gb": 8,
        "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "clear_container", lambda name: True)
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    sleeps, calls = [], []
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    def fake_run(argv, **kwargs):
        if argv[0] == "gh":
            out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
            return subprocess.CompletedProcess(argv, 0, out, "")
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)

    assert pool_script.run("o-kept-1") == 1
    assert sleeps == [pool_script.FAILURE_PAUSE_SECONDS]
    assert any(argv[:3] == ["gh", "api", "--method"] and argv[3] == "DELETE" for argv in calls)


def test_listener_failure_with_exit_zero_deletes_the_runner_and_pauses(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"), "job_cpus": 4, "job_memory_gb": 8,
        "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "clear_container", lambda name: True)
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    sleeps, calls = [], []
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    def fake_run(argv, **kwargs):
        if argv[0] == "gh":
            out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
            return subprocess.CompletedProcess(argv, 0, out, "")
        return subprocess.CompletedProcess(argv, 0)  # run.sh hides the listener failure as exit 0

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)

    assert pool_script.run("o-kept-1") == 1
    assert sleeps == [pool_script.FAILURE_PAUSE_SECONDS]
    assert any(argv[:3] == ["gh", "api", "--method"] and argv[3] == "DELETE" for argv in calls)


def test_a_hung_docker_create_is_cut_off_and_the_slot_fails_so_systemd_restarts_it(
    tmp_path, monkeypatch
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    (bin_dir / "docker").write_text(
        f'#!/bin/sh\necho "$@" >> {log}\n'
        # `create` leaves a container behind and hangs; `ps` lists it until `rm` removes it.
        f'case "$1" in\n create) touch {tmp_path}/created; exec sleep 60;;\n'
        f' rm) touch {tmp_path}/removed;;\n'
        f' ps) [ -e {tmp_path}/created ] && [ ! -e {tmp_path}/removed ] && echo "ci-runner-o-kept-1 created";;\nesac\nexit 0\n'
    )
    (bin_dir / "gh").write_text(
        f'#!/bin/sh\necho gh "$@" >> {log}\n'
        'cat > /dev/null\necho \'{"runner": {"id": 7}, "encoded_jit_config": "jit"}\'\n'
    )
    for script in bin_dir.iterdir():
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"), "job_cpus": 4, "job_memory_gb": 8,
        "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "DOCKER_TIMEOUT", 1)
    real_quiet = pool_script.quiet  # docker and gh run for real; the slot is enabled
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0 if argv[0] == "systemctl" else real_quiet(argv))
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    sleeps = []
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    started = time.monotonic()
    assert pool_script.run("o-kept-1") == 1
    assert time.monotonic() - started < 20
    assert sleeps[-1] == pool_script.FAILURE_PAUSE_SECONDS  # after the 5 s wait for the removal
    lines = log.read_text().splitlines()
    assert any(line.startswith("create ") and "--pull missing" in line for line in lines)
    # The half-created container is removed by name and the runner is deleted.
    assert lines[-1] == "gh api --method DELETE repos/o/kept/actions/runners/7"
    created = next(n for n, line in enumerate(lines) if line.startswith("create "))
    assert "rm --force ci-runner-o-kept-1" in lines[created:]


@pytest.fixture
def watching(tmp_path, monkeypatch):
    """A pool of o/job slots; slot states, containers, and GitHub runners are set by the test."""
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "WATCH_STATE", tmp_path / "watch-state.json")
    (tmp_path / "pool.json").write_text(json.dumps({"repos": [{"repo": "o/job", "slots": 5, "labels": ["x"]}]}))
    world = {"units": {}, "containers": {}, "runners": {}, "restarts": [], "removed": [], "now": 1000.0}
    monkeypatch.setattr(pool_script, "slot_units", lambda: world["units"])
    monkeypatch.setattr(pool_script, "container_states", lambda: world["containers"])
    monkeypatch.setattr(pool_script, "github_runners", lambda repo: world["runners"])
    monkeypatch.setattr(pool_script, "systemctl", lambda *args: world["restarts"].append(args[-1]))
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: world["removed"].append(argv[-1]) or 0)
    monkeypatch.setattr(pool_script.time, "time", lambda: world["now"])
    return world


OFFLINE = {"status": "offline", "busy": False}


def test_watch_restarts_an_offline_slot_without_container_only_on_the_second_sighting_two_minutes_later(
    watching, capsys
):
    watching["units"] = {"o-job-1": ("active", 900)}
    watching["runners"] = {"o-job-1": OFFLINE}

    pool_script.watch()
    assert watching["restarts"] == []  # first sighting: only noted

    watching["now"] += pool_script.MISSING_SECONDS - 1
    pool_script.watch()
    assert watching["restarts"] == []

    watching["now"] += 1
    pool_script.watch()
    assert watching["restarts"] == ["ci-runner@o-job-1.service"]
    assert "restart ci-runner@o-job-1.service: runner offline on GitHub, no container for 120 s" in capsys.readouterr().out


@pytest.mark.parametrize("change", [
    pytest.param({"containers": {"ci-runner-o-job-1": "created"}}, id="a container of any state exists"),
    pytest.param({"runners": {"o-job-1": {"status": "offline", "busy": True}}}, id="GitHub shows a job"),
    pytest.param({"runners": {"o-job-1": {"status": "online", "busy": False}}}, id="runner is online"),
    pytest.param({"runners": {}}, id="GitHub does not list the runner"),
    pytest.param({"units": {"o-job-1": ("active", 299)}}, id="the slot is younger than 5 minutes"),
    pytest.param({"units": {"o-job-1": ("activating", 900)}}, id="the slot is not active"),
])
def test_watch_leaves_a_slot_alone_unless_every_condition_holds(watching, change):
    watching.update({"units": {"o-job-1": ("active", 900)}, "runners": {"o-job-1": OFFLINE}, **change})
    pool_script.watch()
    watching["now"] += 600
    pool_script.watch()
    assert watching["restarts"] == []


def test_a_failed_docker_read_acts_on_nothing_and_forgets_the_first_sighting(watching):
    watching["units"] = {"o-job-1": ("active", 900)}
    watching["runners"] = {"o-job-1": OFFLINE}
    pool_script.watch()  # first sighting
    watching["containers"] = None  # docker timed out
    watching["now"] += 600
    pool_script.watch()
    assert watching["restarts"] == []
    watching["containers"] = {}
    pool_script.watch()  # a successful read starts counting again
    assert watching["restarts"] == []


def test_a_failed_write_leaves_the_old_state_and_an_empty_state_is_forgotten(watching, capsys):
    watching["units"] = {"o-job-1": ("active", 900)}
    watching["runners"] = {"o-job-1": OFFLINE}
    pool_script.watch()  # first sighting, kept
    kept = pool_script.WATCH_STATE.read_text()

    def no_space(path, data, **kwargs):
        path.open("w").close()  # `open` truncated the file, then the write failed
        raise OSError(28, "No space left on device")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pool_script.Path, "write_text", no_space)
        with pytest.raises(OSError):
            pool_script.watch()
    assert pool_script.WATCH_STATE.read_text() == kept  # the old sighting survives the failed write

    pool_script.WATCH_STATE.write_text("")  # what the old writer left behind
    watching["now"] += 600
    pool_script.watch()  # must not crash: the sighting starts again
    assert "is empty" in capsys.readouterr().out
    assert watching["restarts"] == []
    watching["now"] += pool_script.MISSING_SECONDS
    pool_script.watch()
    assert watching["restarts"] == ["ci-runner@o-job-1.service"]


def test_watch_restarts_at_most_two_slots_a_run_and_a_dry_run_changes_nothing(watching, capsys):
    watching["units"] = {f"o-job-{n}": ("active", 900) for n in range(1, 6)}
    watching["runners"] = {f"o-job-{n}": OFFLINE for n in range(1, 6)}
    pool_script.watch()
    watching["now"] += 600

    pool_script.watch(dry_run=True)
    assert watching["restarts"] == []
    assert capsys.readouterr().out.count("would restart") == 2

    pool_script.watch()
    assert len(watching["restarts"]) == 2


def test_watch_removes_a_stuck_container_only_when_its_slot_is_stopped(watching):
    watching["units"] = {"o-job-1": ("active", 900), "o-job-2": ("inactive", 0)}
    watching["containers"] = {"ci-runner-o-job-1": "removing", "ci-runner-o-job-2": "dead",
                              "ci-runner-o-job-3": "removing", "ci-runner-o-job-4": "running"}
    pool_script.watch()
    assert sorted(watching["removed"]) == ["ci-runner-o-job-2", "ci-runner-o-job-3"]


def test_clear_container_stops_removes_and_waits_until_the_daemon_forgets_it(monkeypatch):
    listings = iter([{"ci-runner-s": "running"}, {"ci-runner-s": "removing"}, {}])
    calls, sleeps = [], []
    monkeypatch.setattr(pool_script, "container_states", lambda: next(listings))
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv[1:]) or 0)
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    assert pool_script.clear_container("ci-runner-s")
    assert calls == [["stop", "--time", "60", "ci-runner-s"], ["rm", "--force", "ci-runner-s"]]
    assert len(sleeps) == 2


def test_clear_container_gives_up_when_the_daemon_keeps_listing_it(monkeypatch):
    clock = iter(range(0, 10_000, 50))
    monkeypatch.setattr(pool_script.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pool_script.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0)
    monkeypatch.setattr(pool_script, "container_states", lambda: {"ci-runner-s": "removing"})
    assert not pool_script.clear_container("ci-runner-s")


def test_jobs_start_from_the_official_image_until_the_built_one_exists(monkeypatch):
    built = {**pool_script.DEFAULTS}
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 1)  # `docker image inspect` fails
    assert pool_script.job_image(built) == pool_script.IMAGE
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0)
    assert pool_script.job_image(built) == pool_script.BUILT_IMAGE
    # A custom image is never replaced.
    assert pool_script.job_image({"image": "mine:1"}) == "mine:1"


def test_image_refresh_builds_the_dockerfile_for_the_default_and_pulls_any_other_image(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    calls = []
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv) or 0)
    runs = []

    def fake_run(argv, **kwargs):
        runs.append((argv, kwargs.get("input")))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)

    (tmp_path / "pool.json").write_text("{}")
    assert pool_script.refresh_image() == 0
    argv, stdin = runs[-1]
    assert argv[:3] == ["timeout", "--kill-after=10", str(pool_script.BUILD_TIMEOUT)]
    assert argv[-3:] == ["--tag", pool_script.BUILT_IMAGE, "-"]
    assert stdin == pool_script.DOCKERFILE and stdin.startswith(f"FROM {pool_script.IMAGE}\n")
    assert "postgresql-17" in stdin and "postgresql-18-pgvector" in stdin and "bun.sh/install" in stdin
    assert calls[-1][-3:] == ["image", "prune", "--force"]

    (tmp_path / "pool.json").write_text('{"image": "mine:1"}')
    pool_script.refresh_image()
    argv, stdin = runs[-1]
    assert argv[-3:] == ["pull", "--quiet", "mine:1"] and stdin is None


def test_job_container_mounts_the_package_caches_and_points_the_tools_at_them(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    data = tmp_path / "data"
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(data), "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "clear_container", lambda name: True)
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    scratch = data / "ci-pool/scratch/o-kept-1"
    (scratch / "tmp").mkdir(parents=True)
    (scratch / "tmp/left-by-the-last-job").touch()

    def fake_quiet(argv):
        if argv[:4] == ["sudo", "-n", "rm", "-rf"]:  # the real one needs root for the job's uids
            shutil.rmtree(argv[-1])
        return 0

    monkeypatch.setattr(pool_script, "quiet", fake_quiet)
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    monkeypatch.setattr(pool_script.time, "sleep", lambda seconds: None)
    created = []

    def fake_run(argv, **kwargs):
        if argv[0] == "gh":
            out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
            return subprocess.CompletedProcess(argv, 0, out, "")
        if "create" in argv:
            created.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    pool_script.run("o-kept-1")

    (argv,) = created
    mounts = {a for a in argv if a.startswith(str(data))}
    root = data / "ci-pool"
    assert f"{root / 'apt/o-kept-1/archives'}:/var/cache/apt/archives" in mounts
    for name, target in (("tmp", "/tmp"), ("postgresql", "/var/lib/postgresql"), ("bun", "/home/runner/.bun")):
        assert f"{scratch / name}:{target}" in mounts
        assert (scratch / name).stat().st_mode & 0o7777 == 0o1777
    assert not (scratch / "tmp/left-by-the-last-job").exists()
    assert f"{root / 'cache/o-kept/cargo-registry'}:/home/runner/.cargo/registry" in mounts
    assert all(Path(m.split(":")[0]).is_dir() for m in mounts)
    assert "BUN_INSTALL_CACHE_DIR=/home/runner/.cache/bun" in argv


@pytest.mark.parametrize("userns", [False, True])
def test_a_dind_slot_gives_the_job_its_own_daemon_and_removes_it_after_the_job(
    tmp_path, monkeypatch, userns
):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    data = tmp_path / "data"
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(data),
        "repos": [{"repo": "o/e", "slots": 1, "labels": ["x"], "docker": "dind", "userns": userns}],
    }))
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    monkeypatch.setattr(pool_script.time, "sleep", lambda seconds: None)
    calls = []
    monkeypatch.setattr(pool_script, "clear_container", lambda name: calls.append(["clear", name]) or True)
    monkeypatch.setattr(pool_script, "quiet", lambda argv: calls.append(argv) or 0)

    def fake_run(argv, **kwargs):
        if argv[0] == "gh":
            out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
            return subprocess.CompletedProcess(argv, 0, out, "")
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    pool_script.run("o-e-1")

    sidecar = next(argv for argv in calls if pool_script.DIND_IMAGE in argv)
    job = next(argv for argv in calls if "--init" in argv)
    assert "--privileged" in sidecar and "--privileged" not in job
    # Only a userns repository's sidecar gets the pool profile; the job container never does.
    assert (f"apparmor={pool_script.USERNS_PROFILE}" in sidecar) == userns
    assert "--security-opt" not in job
    assert sidecar[sidecar.index("--network") + 1] == "ci-dind-o-e-1"
    assert sidecar[sidecar.index("--memory") + 1] == job[job.index("--memory") + 1] == "8g"
    assert job[job.index("--network") + 1] == "container:ci-dind-o-e-1"
    assert "DOCKER_HOST=tcp://localhost:2376" in job
    assert f"{data / 'ci-pool/dind/o-e-1/certs/client'}:/certs/client:ro" in job
    assert not any("docker.sock" in arg for argv in calls for arg in argv)
    # The sidecar and its network go after the job container, in the same cleanup.
    tail = [argv for argv in calls if argv[0] == "clear" or argv[1:3] == ["network", "rm"]][-3:]
    assert tail == [["clear", "ci-runner-o-e-1"], ["clear", "ci-dind-o-e-1"],
                    ["docker", "network", "rm", "ci-dind-o-e-1"]]


@pytest.fixture
def sudo(tmp_path, monkeypatch):
    """`sudo -n` as the pool sees it: apparmor_parser loads the profile from the file it is
    given; install copies that file. `refuse` names the command sudo rejects."""
    path = tmp_path / "apparmor.d" / pool_script.USERNS_PROFILE
    monkeypatch.setattr(pool_script, "USERNS_PROFILE_PATH", path)
    state = {"loaded": [], "refuse": None}

    def fake_run(argv, **kwargs):
        assert argv[:2] == ["sudo", "-n"]
        if argv[2] == state["refuse"]:
            return subprocess.CompletedProcess(argv, 1)
        if argv[2] == "apparmor_parser":
            state["loaded"].append(Path(argv[-1]).read_text())
        else:
            assert argv[2:5] == ["install", "-m", "0644"]
            path.parent.mkdir(exist_ok=True)
            path.write_text(Path(argv[5]).read_text())
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    return path, state


def test_apply_loads_and_installs_the_sidecar_profile_once_when_a_repository_asks_for_it(
    slots, sudo, capsys
):
    data, calls, apply = slots
    path, state = sudo
    userns = [{"repo": "o/kept", "slots": 2, "labels": ["x"], "docker": "dind", "userns": True}]

    assert apply() == 0
    assert state["loaded"] == [] and f"write {path}" not in capsys.readouterr().out
    assert apply(check=True, repos=userns) == 0
    assert state["loaded"] == [] and not path.exists()
    assert f"write {path}" in capsys.readouterr().out
    assert apply(repos=userns) == 0
    assert state["loaded"] == [pool_script.USERNS_PROFILE_TEXT]
    assert path.read_text() == pool_script.USERNS_PROFILE_TEXT
    assert f"write {path}" in capsys.readouterr().out
    assert apply(repos=userns) == 0
    assert state["loaded"] == [pool_script.USERNS_PROFILE_TEXT]
    assert f"write {path}" not in capsys.readouterr().out


@pytest.mark.parametrize("refuse", ["apparmor_parser", "install"])
def test_a_refused_profile_leaves_the_pool_and_the_profile_directory_unchanged(
    slots, sudo, tmp_path, refuse
):
    data, calls, apply = slots
    path, state = sudo
    state["refuse"] = refuse
    userns = [{"repo": "o/kept", "slots": 2, "labels": ["x"], "docker": "dind", "userns": True}]

    with pytest.raises(SystemExit, match=rf"`sudo -n {refuse}` exited 1"):
        apply(repos=userns)

    assert not path.exists()
    assert not (tmp_path / "pool.json").exists()
    assert not (tmp_path / "job-started.sh").exists()
    assert calls == []
    assert sorted(p.name for p in (tmp_path / "units/default.target.wants").iterdir()) == [
        "ci-runner@o-gone-1.service", "ci-runner@o-kept-1.service"]
    assert (data / "ci-pool/work/o-gone-1").is_dir()
    # The next apply, once sudo allows both commands, completes the same change.
    state["refuse"] = None
    assert apply(repos=userns) == 0
    assert path.read_text() == pool_script.USERNS_PROFILE_TEXT and (tmp_path / "pool.json").exists()


def test_userns_requires_a_dind_repository(configuration):
    configuration["crewship"]["ci_pool"]["repos"].append(
        {"repo": "o/plain", "slots": 1, "labels": ["plain"], "userns": True}
    )
    with pytest.raises(Exception, match=r"repos\.1 \(dependentRequired\)"):
        ship.validate_config(configuration)


def test_a_slot_does_not_kill_the_job_of_its_previous_container(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    (tmp_path / "pool.json").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"), "repos": [{"repo": "o/kept", "slots": 1, "labels": ["x"]}],
    }))
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0)
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-kept-1")  # a Runner.Worker runs
    monkeypatch.setattr(pool_script, "clear_container", lambda name: pytest.fail("removed a running job"))
    monkeypatch.setattr(pool_script.signal, "signal", lambda *args: None)
    sleeps, runs = [], []
    monkeypatch.setattr(pool_script.time, "sleep", sleeps.append)

    def fake_run(argv, **kwargs):
        runs.append(argv)
        out = json.dumps({"runner": {"id": 7}, "encoded_jit_config": "jit"})
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    assert pool_script.run("o-kept-1") == 1
    assert not any("create" in argv for argv in runs)
    assert sleeps == [pool_script.FAILURE_PAUSE_SECONDS]
