import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cf = load("cf_runner", "blueprint/maintenance/cf-runner.py")
ship = load("ship_config_cf_runner", "scripts/ship.py")

CONFIG = {**cf.DEFAULTS, "repos": [{"repo": "o/a", "label": "cf-a"}]}


def job(job_id, status="queued", repo="o/a"):
    return {"id": job_id, "status": status, "repo": repo, "labels": ["cf-a"]}


def test_plan_gives_each_queued_job_one_runner_once():
    state = {}
    assert cf.plan([job(1), job(2), job(3, "in_progress")], state, 1000, CONFIG) == [1, 2]
    state = {"1": {"repo": "o/a", "at": 1000, "tries": 1, "runner": 9}}
    assert cf.plan([job(1), job(2)], state, 1010, CONFIG) == [2]


def test_plan_respects_the_cap_counting_running_jobs():
    config = {**CONFIG, "max_instances": 2}
    state = {"1": {"repo": "o/a", "at": 1000, "tries": 1, "runner": 9}}
    assert cf.plan([job(1, "in_progress"), job(2), job(3)], state, 1010, config) == [2]


def test_plan_retries_a_stuck_job_after_the_wait_up_to_max_tries():
    state = {"1": {"repo": "o/a", "at": 1000, "tries": 1, "runner": 9}}
    assert cf.plan([job(1)], state, 1000 + CONFIG["retry_after_seconds"], CONFIG) == [1]
    state["1"]["tries"] = CONFIG["max_tries"]
    assert cf.plan([job(1)], state, 10**6, CONFIG) == []


def test_a_retry_does_not_count_twice_against_the_cap():
    config = {**CONFIG, "max_instances": 1}
    state = {"1": {"repo": "o/a", "at": 0, "tries": 1, "runner": 9}}
    assert cf.plan([job(1)], state, 10**6, config) == [1]


def test_failed_dispatch_does_not_hold_a_slot():
    config = {**CONFIG, "max_instances": 1}
    state = {"1": {"repo": "o/a", "at": 1000, "tries": 1, "failed": True}}
    assert cf.plan([job(1), job(2)], state, 1010, config) == [2]


def test_failed_container_start_deletes_the_registered_runner(monkeypatch):
    calls = []

    def fake_gh(*args, payload=None):
        calls.append(args)
        return {"encoded_jit_config": "jit", "runner": {"id": 7}}

    def refuse(*_):
        raise cf.urllib.error.URLError("down")

    monkeypatch.setattr(cf, "gh", fake_gh)
    monkeypatch.setattr(cf, "start_container", refuse)
    monkeypatch.setattr(cf.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="cf-5"):
        cf.dispatch_job("o/a", "cf-a", 5, "https://w", "t")
    assert calls[-1] == ("--method", "DELETE", "repos/o/a/actions/runners/7")


def test_poll_dispatches_and_records_the_runner(monkeypatch, tmp_path):
    (tmp_path / "worker-url").write_text("https://w\n")
    (tmp_path / "dispatch-token").write_text("t\n")
    config = {**CONFIG, "state_dir": str(tmp_path)}
    monkeypatch.setattr(cf, "repo_jobs", lambda repo, label: [job(4)])
    monkeypatch.setattr(cf, "dispatch_job", lambda *args: 11)
    state = cf.poll(config, {}, now=1000)
    assert state == {"4": {"repo": "o/a", "at": 1000, "tries": 1, "runner": 11}}


def test_source_hash_follows_settings_and_files(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM x\n")
    config = {**CONFIG, "source_dir": str(tmp_path)}
    first = cf.source_hash(config)
    assert cf.source_hash(config) == first
    assert cf.source_hash({**config, "max_instances": 9}) != first
    (tmp_path / "Dockerfile").write_text("FROM y\n")
    assert cf.source_hash(config) != first


def test_read_env_file_takes_export_and_quotes(tmp_path):
    path = tmp_path / "env"
    path.write_text("# c\nexport A='x y'\nB=\"z\"\nC=1\n")
    assert cf.read_env_file(path) == {"A": "x y", "B": "z", "C": "1"}


def test_wrangler_config_sets_instance_type_and_cap():
    container = cf.wrangler_config(CONFIG)["containers"][0]
    assert (container["instance_type"], container["max_instances"]) == ("standard-4", 4)


@pytest.mark.parametrize(
    ("block", "error"),
    [
        ({"repos": [{"repo": "o/a", "label": "linux"}]}, "label"),
        ({"repos": [{"repo": "o/a", "label": "ubuntu-latest"}]}, "label"),
        ({"repos": [{"repo": "o/a", "label": "x"}, {"repo": "O/A", "label": "y"}]}, "twice"),
        ({"repos": [{"repo": "o/a", "label": "x"}], "credentials_file": "/a/../b"}, "traverse"),
    ],
)
def test_ship_refuses_bad_cloudflare_runner_blocks(block, error):
    config = {"cloudflare_runner": {"credentials_file": "/home/u/env", **block}}
    with pytest.raises(ValueError, match=error):
        ship.validate_cloudflare_runner(config)


def test_ship_accepts_a_good_block():
    ship.validate_cloudflare_runner(
        {"cloudflare_runner": {"credentials_file": "/home/u/env", "repos": [{"repo": "o/a", "label": "cf-a"}]}}
    )
    assert json.dumps(CONFIG)


def test_deploy_refuses_while_a_dispatched_job_is_in_flight(monkeypatch, tmp_path):
    state_dir, source = tmp_path / "state", tmp_path / "src"
    state_dir.mkdir()
    source.mkdir()
    (state_dir / "state.json").write_text(json.dumps({"1": {"repo": "o/a", "at": 1, "tries": 1}}))
    config = {**CONFIG, "state_dir": str(state_dir), "source_dir": str(source), "credentials_file": "/none"}
    monkeypatch.setattr(cf, "repo_jobs", lambda repo, label: [job(1, "in_progress")])
    with pytest.raises(SystemExit, match="1 job"):
        cf.deploy(config)
    (state_dir / "deployed").write_text(cf.source_hash(config))
    cf.deploy(config)  # unchanged source and settings: nothing to do, no listing needed


def test_repo_jobs_reads_a_run_without_our_label_once(monkeypatch):
    cf.NOT_OURS.clear()
    calls = []

    def fake_gh(path, *args, payload=None):
        calls.append(path)
        if path.endswith("per_page=30"):
            return {"workflow_runs": [
                {"id": 1, "status": "in_progress"}, {"id": 2, "status": "completed"}, {"id": 3, "status": "queued"}]}
        labels = ["cf-a"] if "/runs/3/" in path else ["ubuntu-latest"]
        return {"jobs": [{"id": 10, "status": "queued", "labels": labels}]}

    monkeypatch.setattr(cf, "gh", fake_gh)
    monkeypatch.setattr(cf, "gh_cached", fake_gh)
    assert [j["id"] for j in cf.repo_jobs("o/a", "cf-a")] == [10]
    cf.repo_jobs("o/a", "cf-a")
    assert sum("/runs/1/" in c for c in calls) == 1
    assert not any("/runs/2/" in c for c in calls)


def test_gh_cached_sends_the_etag_and_reuses_the_body_on_304(monkeypatch):
    cf.ETAGS.clear()
    sent = []
    answers = [
        ('HTTP/2.0 200 OK\r\nEtag: W/"a"\r\n\r\n{"workflow_runs": [1]}', 0),
        ("HTTP/2.0 304 Not Modified\r\nEtag: W/\"a\"\r\n\r\n", 1),
    ]

    def fake_run(cmd, **kwargs):
        sent.append(cmd)
        out, code = answers.pop(0)
        return subprocess.CompletedProcess(cmd, code, out, "")

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    assert cf.gh_cached("repos/o/a/actions/runs") == {"workflow_runs": [1]}
    assert cf.gh_cached("repos/o/a/actions/runs") == {"workflow_runs": [1]}
    assert "If-None-Match" not in " ".join(sent[0])
    assert 'If-None-Match: W/"a"' in sent[1]
