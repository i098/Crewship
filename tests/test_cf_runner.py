import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

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


# --- shared-cluster (`kvz`) backend ---

KVZ = {**cf.KVZ_DEFAULTS, "ssh": "u@h", "node": ["node-a", "node-b"], "image": "img"}
KVZ_CONFIG = {**cf.DEFAULTS, "repos": [{"repo": "o/a", "label": "kvz-a", "kvz": KVZ}]}
NS = KVZ["namespace"]
needs_jq = pytest.mark.skipif(not shutil.which("jq"), reason="the idle check needs jq")


def node(name="node-a", ready="True", **pressure):
    conditions = [{"type": "Ready", "status": ready}] + [{"type": k, "status": v} for k, v in pressure.items()]
    return {"kind": "Node", "metadata": {"name": name},
            "status": {"conditions": conditions, "allocatable": {"cpu": "10", "memory": "16Gi"}}}


def pod(name, ns="other", on="node-a", phase="Running", cpu="1", memory="1Gi"):
    spec = {"nodeName": on, "containers": [{"resources": {"requests": {"cpu": cpu, "memory": memory}}}]}
    return {"kind": "Pod", "metadata": {"name": name, "namespace": ns}, "spec": spec, "status": {"phase": phase}}


def kjob(name, done=False):
    return {"kind": "Job", "metadata": {"name": name, "namespace": NS},
            "status": {"completionTime": "t"} if done else {}}


def idle(items, target="node-a", max_jobs=1):
    snapshot = json.dumps({"items": items})
    run = subprocess.run(
        [str(cf.IDLE_CHECK), target, NS, str(max_jobs), "60", "60"], input=snapshot, capture_output=True, text=True)
    return run.returncode, run.stdout.strip()


@needs_jq
def test_idle_check_is_free_for_a_quiet_ready_node():
    assert idle([node(), pod("p", cpu="1")]) == (0, "FREE")


@needs_jq
@pytest.mark.parametrize(
    ("items", "reason"),
    [
        ([], "node missing"),
        ([node(ready="False")], "not Ready"),
        ([node(DiskPressure="True")], "pressure DiskPressure"),
        ([node(), pod("w", phase="Pending", on="")], "other pod pending"),
        ([node(), pod("w", phase="Pending", on="node-b")], None),
        ([node(), pod("big", cpu="7")], "cpu requested"),
        ([node(), pod("big", memory="12Gi")], "memory requested"),
    ],
)
def test_idle_check_is_busy_for_each_condition(items, reason):
    code, out = idle(items)
    if reason is None:
        assert (code, out) == (0, "FREE")  # a pod pending for another node does not block this one
    else:
        assert code != 0 and out.startswith("BUSY") and reason in out


@needs_jq
def test_idle_check_caps_the_jobs_of_ours_and_ignores_finished_ones():
    assert idle([node(), kjob("a")])[0] != 0
    assert idle([node(), kjob("a", done=True)]) == (0, "FREE")
    assert idle([node(), kjob("a"), kjob("b")], max_jobs=3) == (0, "FREE")
    assert idle([node(), kjob("a"), kjob("b")], max_jobs=2)[0] != 0


@needs_jq
def test_idle_check_never_says_free_for_unreadable_input():
    run = subprocess.run([str(cf.IDLE_CHECK), "node-a", NS, "1", "60", "60"], input="nope", capture_output=True, text=True)
    assert run.returncode != 0 and "FREE" not in run.stdout


def test_cluster_idle_picks_the_first_free_node_and_treats_errors_as_busy(monkeypatch):
    class Verdict:
        def __init__(self, code):
            self.returncode = code

    monkeypatch.setattr(cf, "kvz_kubectl", lambda *a, **k: "{}")
    monkeypatch.setattr(cf.subprocess, "run", lambda cmd, **k: Verdict(0 if cmd[1] == "node-b" else 1))
    assert cf.cluster_idle(KVZ) == "node-b"
    monkeypatch.setattr(cf.subprocess, "run", lambda cmd, **k: Verdict(1))
    assert cf.cluster_idle(KVZ) is None

    def broken(*a, **k):
        raise RuntimeError("ssh down")

    monkeypatch.setattr(cf, "kvz_kubectl", broken)
    assert cf.cluster_idle(KVZ) is None
    monkeypatch.setattr(cf, "kvz_kubectl", lambda *a, **k: "{}")

    def missing(*a, **k):
        raise FileNotFoundError("kvz-idle-check.sh")

    monkeypatch.setattr(cf.subprocess, "run", missing)
    assert cf.cluster_idle(KVZ) is None


class Backend:
    """Records what dispatch_kvz does instead of touching a cluster or Docker."""

    def __init__(self, monkeypatch, node=None, cluster_fails=False, local_fails=False):
        self.calls = []
        monkeypatch.setattr(cf, "gh", self.gh)
        monkeypatch.setattr(cf, "cluster_idle", lambda kvz: self.calls.append("idle") or node)
        monkeypatch.setattr(cf, "start_cluster", lambda *a: self.fail("cluster") if cluster_fails else self.calls.append("cluster"))
        monkeypatch.setattr(cf, "delete_cluster_objects", lambda kvz, name: self.calls.append(f"delete-objects {name}"))
        monkeypatch.setattr(cf, "start_local", lambda *a: self.fail("local") if local_fails else self.calls.append("local"))

    def gh(self, *args, payload=None):
        self.calls.append(args[-1] if args[0] == "--method" else "register")
        return {"encoded_jit_config": "jit", "runner": {"id": 7}}

    def fail(self, where):
        self.calls.append(where)
        raise RuntimeError(f"{where} down")


def kjob_in(event="push", fork=False):
    return {"id": 5, "repo": "o/a", "event": event, "fork": fork}


ENTRY = KVZ_CONFIG["repos"][0]


def test_dispatch_starts_on_the_cluster_only_when_idle(monkeypatch):
    backend = Backend(monkeypatch, node="node-a")
    assert cf.dispatch_kvz(ENTRY, kjob_in(), 1) == (7, "cluster")
    assert backend.calls == ["register", "idle", "cluster"]


def test_dispatch_falls_back_to_this_host_when_busy_or_unreadable(monkeypatch):
    backend = Backend(monkeypatch, node=None)  # cluster_idle returns None for both busy and error
    assert cf.dispatch_kvz(ENTRY, kjob_in(), 1) == (7, "local")
    assert "cluster" not in backend.calls


@pytest.mark.parametrize(
    "job_kwargs", [{"fork": True}, {"event": "pull_request_target"}, {"event": "workflow_run"}]
)
def test_dispatch_never_sends_unsafe_jobs_to_the_cluster(monkeypatch, job_kwargs):
    backend = Backend(monkeypatch, node="node-a")
    assert cf.dispatch_kvz(ENTRY, kjob_in(**job_kwargs), 1) == (7, "local")
    assert "idle" not in backend.calls and "cluster" not in backend.calls


def test_failed_cluster_start_deletes_its_objects_and_runs_here(monkeypatch):
    backend = Backend(monkeypatch, node="node-a", cluster_fails=True)
    assert cf.dispatch_kvz(ENTRY, kjob_in(), 2) == (7, "local")
    assert "delete-objects kvz-5-2" in backend.calls and backend.calls[-1] == "local"


def test_failed_local_start_deletes_the_runner(monkeypatch):
    backend = Backend(monkeypatch, node=None, local_fails=True)
    with pytest.raises(RuntimeError, match="local down"):
        cf.dispatch_kvz(ENTRY, kjob_in(), 1)
    assert backend.calls[-1] == "repos/o/a/actions/runners/7"


def test_manifest_keeps_the_runner_config_in_the_secret_only():
    items = cf.kvz_manifest(KVZ, "kvz-5-1", "SECRET-JIT", "node-a")["items"]
    secret, job = items
    assert secret["stringData"] == {"JITCONFIG": "SECRET-JIT"}
    assert "SECRET-JIT" not in json.dumps(job)
    pod_spec = job["spec"]["template"]["spec"]
    assert pod_spec["nodeSelector"] == {"kubernetes.io/hostname": "node-a"}
    assert pod_spec["restartPolicy"] == "Never" and job["spec"]["backoffLimit"] == 0
    assert "securityContext" not in pod_spec["containers"][0] and "hostPath" not in json.dumps(job)


class Cluster:
    def __init__(self, monkeypatch, jobs):
        self.deleted = []
        listing = json.dumps({"items": jobs})
        monkeypatch.setattr(cf, "kvz_kubectl", lambda kvz, *a, **k: listing)
        monkeypatch.setattr(cf, "delete_cluster_objects", lambda kvz, name: self.deleted.append(name))
        monkeypatch.setattr(cf, "delete_runner", lambda repo, runner: self.deleted.append(f"runner {runner}"))


def entry_state(name="kvz-5-1", **extra):
    return {"5": {"repo": "o/a", "at": 1, "tries": 1, "runner": 7, "where": "cluster", "name": name, **extra}}


def item(name, **status):
    return {"metadata": {"name": name}, "status": status}


def test_cleanup_deletes_finished_jobs_their_secret_and_runner(monkeypatch):
    for status in ({"completionTime": "t"}, {"conditions": [{"type": "Failed", "status": "True"}]}):
        cluster = Cluster(monkeypatch, [item("kvz-5-1", **status)])
        state = entry_state()
        cf.cleanup_cluster(ENTRY, state)
        assert cluster.deleted == ["kvz-5-1", "runner 7"] and state["5"]["cleaned"]


def test_cleanup_leaves_a_running_job_and_a_cleaned_entry_alone(monkeypatch):
    cluster = Cluster(monkeypatch, [item("kvz-5-1", active=1)])
    state = entry_state()
    cf.cleanup_cluster(ENTRY, state)
    assert cluster.deleted == [] and "cleaned" not in state["5"]
    cf.cleanup_cluster(ENTRY, entry_state(cleaned=True))
    assert cluster.deleted == []


def test_cleanup_also_removes_the_secret_of_a_job_that_expired(monkeypatch):
    cluster = Cluster(monkeypatch, [])
    cf.cleanup_cluster(ENTRY, entry_state())
    assert cluster.deleted == ["kvz-5-1", "runner 7"]


def test_poll_records_where_a_kvz_job_started_and_needs_no_worker(monkeypatch, tmp_path):
    config = {**KVZ_CONFIG, "state_dir": str(tmp_path)}
    monkeypatch.setattr(cf, "repo_jobs", lambda repo, label: [{**job(4), "labels": ["kvz-a"]}])
    monkeypatch.setattr(cf, "dispatch_kvz", lambda entry, job, tries: (11, "cluster"))
    monkeypatch.setattr(cf, "cleanup_cluster", lambda entry, state: None)
    state = cf.poll(config, {}, now=1000)
    assert state == {"4": {"repo": "o/a", "at": 1000, "tries": 1, "runner": 11, "where": "cluster", "name": "kvz-4-1"}}


def test_repo_jobs_marks_fork_and_event_from_the_run(monkeypatch):
    cf.NOT_OURS.clear()
    runs = [
        {"id": 1, "status": "queued", "event": "push", "head_repository": {"full_name": "O/a"}},
        {"id": 2, "status": "queued", "event": "pull_request", "head_repository": {"full_name": "x/a"}},
        {"id": 3, "status": "queued", "event": "pull_request", "head_repository": None},
    ]
    monkeypatch.setattr(cf, "gh_cached", lambda path: {"workflow_runs": runs})
    monkeypatch.setattr(cf, "gh", lambda path, **k: {"jobs": [{"id": int(path.split("/runs/")[1][0]) * 10, "labels": ["kvz-a"]}]})
    found = {j["id"]: (j["event"], j["fork"]) for j in cf.repo_jobs("o/a", "kvz-a")}
    assert found == {10: ("push", False), 20: ("pull_request", True), 30: ("pull_request", True)}


def test_load_config_fills_kvz_defaults(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"repos": [{"repo": "o/a", "label": "k", "kvz": {"ssh": "u@h", "node": ["n"], "image": "i"}},
                                          {"repo": "o/b", "label": "c"}]}))
    repos = cf.load_config(path)["repos"]
    assert repos[0]["kvz"]["max"] == 1 and repos[0]["kvz"]["namespace"] == "crewship-ci" and "kvz" not in repos[1]


def test_deploy_has_nothing_to_do_when_every_repository_uses_the_cluster(tmp_path):
    cf.deploy({**KVZ_CONFIG, "state_dir": str(tmp_path), "source_dir": str(tmp_path)})
    assert not list(tmp_path.iterdir())


def kvz_document(**kvz):
    block = {"ssh": "u@h", "node": ["node-a"], "image": "img", **kvz}
    base = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    base["crewship"]["cloudflare_runner"] = {"repos": [{"repo": "o/a", "label": "kvz-a", "kvz": block}]}
    return base


def test_schema_accepts_a_linux_kvz_block_and_refuses_macos():
    ship.validate_document(kvz_document(os="linux"), "crewship.schema.json")
    with pytest.raises(ValueError, match="kvz.os"):
        ship.validate_document(kvz_document(os="macos"), "crewship.schema.json")


def test_credentials_file_is_needed_only_for_repositories_without_kvz():
    ship.validate_cloudflare_runner(kvz_document()["crewship"])
    plain = {"cloudflare_runner": {"repos": [{"repo": "o/a", "label": "cf-a"}]}}
    with pytest.raises(ValueError, match="credentials_file"):
        ship.validate_cloudflare_runner(plain)
