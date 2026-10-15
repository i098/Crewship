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
    for path in ("ci-pool/work/o-kept-1", "ci-pool/work/o-gone-1", "ci-pool/cache/o-kept",
                 "ci-pool/cache/o-gone", "work/projects", "cache/models"):
        (data / path).mkdir(parents=True)
    monkeypatch.setattr(pool_script, "CONFIG", tmp_path / "pool.json")
    monkeypatch.setattr(pool_script, "TEMPLATE", units / "ci-runner@.service")
    monkeypatch.setattr(pool_script, "WANTS", wants)
    monkeypatch.setattr(pool_script, "HOOK", tmp_path / "job-started.sh")
    monkeypatch.setattr(pool_script, "busy", lambda name: False)
    monkeypatch.setattr(pool_script, "remove_tree", shutil.rmtree)
    for attr, text in (("WATCH_SERVICE", pool_script.WATCH_SERVICE_TEXT),
                       ("WATCH_TIMER", pool_script.WATCH_TIMER_TEXT)):
        monkeypatch.setattr(pool_script, attr, units / getattr(pool_script, attr).name)
        getattr(pool_script, attr).write_text(text)
    monkeypatch.setattr(pool_script, "quiet", lambda argv: 0)  # the watch timer is enabled
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
    assert not (data / "ci-pool/cache/o-gone").exists()
    assert (data / "ci-pool/work/o-kept-1").is_dir()
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
            "" if ok else "Couldn't find PID field in ps output" if listing else "No such container",
        )

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    assert not pool_script.busy("idle")
    assert pool_script.busy("busy")
    assert not pool_script.busy("missing")


def test_a_drained_slot_keeps_its_repository_cache_while_it_is_busy(slots, monkeypatch):
    data, calls, apply = slots
    monkeypatch.setattr(pool_script, "busy", lambda name: name == "o-gone-1")

    assert apply(repos=[]) == 0

    assert (data / "ci-pool/work/o-gone-1").is_dir()
    assert (data / "ci-pool/cache/o-gone").is_dir()
    assert not (data / "ci-pool/work/o-kept-1").exists()
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
        f'#!/bin/sh\necho "$@" >> {log}\n[ "$1" = create ] && exec sleep 60\nexit 0\n'
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
    assert sleeps == [pool_script.FAILURE_PAUSE_SECONDS]
    lines = log.read_text().splitlines()
    assert any(line.startswith("create ") and "--pull missing" in line for line in lines)
    # The half-created container is removed by name and the runner is deleted.
    assert lines[-2:] == ["rm --force ci-runner-o-kept-1", "gh api --method DELETE repos/o/kept/actions/runners/7"]


@pytest.mark.parametrize(("age", "running", "restart"), [
    (601, False, True),    # registered long ago, no container: stalled
    (599, False, False),   # still inside the grace period
    (900, True, False),    # a job or an idle listener runs
    (900, None, False),    # docker did not answer: unknown is not stalled
])
def test_stalled_slot_decision(age, running, restart):
    assert pool_script.stalled(age, running) is restart


def test_watch_restarts_only_stalled_slots_and_pulls_the_image_once_an_hour(
    tmp_path, monkeypatch, capsys
):
    wants = tmp_path / "wants"
    wants.mkdir()
    ages = {"o-stuck-1": 700, "o-job-1": 700, "o-new-1": 30}
    for name in ages:
        (wants / f"ci-runner@{name}.service").touch()
    monkeypatch.setattr(pool_script, "WANTS", wants)
    monkeypatch.setattr(pool_script, "PULL_STAMP", tmp_path / "last-pull")
    monkeypatch.setattr(pool_script, "docker", lambda: ["docker"])
    pulls, restarts = [], []

    def fake_run(argv, **kwargs):
        if argv[:3] == ["systemctl", "--user", "show"]:
            age = ages[argv[3][len("ci-runner@"):-len(".service")]]
            out = f"ActiveState=active\nActiveEnterTimestampMonotonic={int((time.monotonic() - age) * 1e6)}\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        pulls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pool_script.subprocess, "run", fake_run)
    running = {"o-stuck-1": False, "o-job-1": True, "o-new-1": False}
    monkeypatch.setattr(pool_script, "container_running", running.get)
    monkeypatch.setattr(pool_script, "systemctl", lambda *args: restarts.append(args))

    assert pool_script.watch() == 0
    assert restarts == [("restart", "ci-runner@o-stuck-1.service")]
    assert "restart ci-runner@o-stuck-1.service" in capsys.readouterr().out
    assert len(pulls) == 1 and pulls[0][-3:] == ["pull", "--quiet", pool_script.IMAGE]

    pool_script.watch()
    assert len(pulls) == 1  # stamped: no second pull within the hour
