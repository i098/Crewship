#!/usr/bin/env python3
"""Cloudflare container runner: one fresh Cloudflare Container for each GitHub Actions job.

  cf-runner.py dispatch [--once]   run by cf-runner-dispatch.service: polls the configured
                                   repositories for queued jobs that ask for a repository's
                                   label, mints one JIT runner for each and starts one container.
  cf-runner.py deploy              builds and deploys the Worker and its container image when
                                   the source or config changed; refuses while a job is in flight.

The GitHub token never leaves the host (`gh` login); only the JIT runner config goes to the
Worker. GitHub removes a JIT runner after its one job. docs/cloudflare-runner.md is the guide.
A repository entry with a `kvz` block uses a shared Kubernetes cluster instead of the Worker, but
only while kvz-idle-check.sh says the cluster is idle; otherwise the same runner starts on this host.
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("CF_RUNNER_CONFIG", HOME / ".config/cf-runner/config.json"))
WORKER = "crewship-cf-runner"
INSTANCE_TYPE = "standard-4"
DEFAULTS = {
    "max_instances": 4,
    "poll_seconds": 60,
    "retry_after_seconds": 900,
    "max_tries": 3,
}
# A job that finished long ago is no longer interesting; its state entry goes after this.
FORGET_SECONDS = 86400
START_ATTEMPTS = 2
HTTP_TIMEOUT = 60
BASE_LABELS = ["self-hosted", "linux"]
# Per-repository `kvz` block defaults (the schema allows only Linux jobs).
KVZ_DEFAULTS = {"namespace": "crewship-ci", "max": 1, "cpu": "2", "memory": "4Gi", "cpu_pct": 60, "mem_pct": 60}
# Jobs of these events run someone else's code or read secrets: never on the shared cluster.
KVZ_NEVER_EVENTS = {"pull_request_target", "workflow_run"}
IDLE_CHECK = Path(__file__).with_name("kvz-idle-check.sh")
RUNNER_COMMAND = ["sh", "-c", 'exec /home/runner/run.sh --jitconfig "$JITCONFIG"']


def load_config(path=CONFIG):
    config = {**DEFAULTS, **json.loads(Path(path).read_text())}
    config.setdefault("state_dir", str(HOME / ".local/state/cf-runner"))
    config.setdefault("source_dir", str(HOME / ".local/share/cf-runner/src"))
    config["repos"] = [
        {**entry, "kvz": {**KVZ_DEFAULTS, **entry["kvz"]}} if entry.get("kvz") else entry for entry in config["repos"]
    ]
    return config


def plan(jobs, state, now, config):
    """Ids of queued jobs to give a runner now: never given one, or given one too long ago, within the cap."""
    live = {job["id"] for job in jobs if job["status"] in ("queued", "in_progress")}
    busy = sum(1 for key, entry in state.items() if int(key) in live and not entry.get("failed"))
    chosen = []
    for job in jobs:
        entry = state.get(str(job["id"]))
        if job["status"] != "queued" or (
            entry and (entry["tries"] >= config["max_tries"] or now - entry["at"] < config["retry_after_seconds"])
        ):
            continue
        # A retry replaces an entry that already counts as busy.
        extra = 0 if entry and not entry.get("failed") else 1
        if extra and busy >= config["max_instances"]:
            continue
        busy += extra
        chosen.append(job["id"])
    return chosen


# Reads go through the GitHub App token (gh-read-token run), which falls back to the user login when the
# app is not configured or cannot answer. JIT runners need the user login, so writes never use it.
APP_TOKEN = Path(__file__).with_name("gh-read-token")


def gh(*args, payload=None):
    read = payload is None and "--method" not in args
    result = subprocess.run(
        [*([str(APP_TOKEN), "run"] if read and APP_TOKEN.exists() else []), "gh", "api", *args]
        + (["--input", "-"] if payload is not None else []),
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=HTTP_TIMEOUT,
    )
    if result.returncode:
        raise RuntimeError(f"gh api {args[-1]}: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


# A 304 answer to a conditional request does not count against the GitHub REST budget, so an idle
# repository costs nothing per poll. Keyed by path: (etag, parsed body).
ETAGS = {}


def gh_cached(path):
    """gh(path), sent with If-None-Match once an ETag is known; a 304 returns the last body."""
    etag, body = ETAGS.get(path, (None, None))
    args = ["api", "-i", path] + (["-H", f"If-None-Match: {etag}"] if etag else [])
    result = subprocess.run(
        [*([str(APP_TOKEN), "run"] if APP_TOKEN.exists() else []), "gh", *args],
        capture_output=True, text=True, timeout=HTTP_TIMEOUT,
    )
    if etag and " 304" in result.stdout.partition("\n")[0]:
        return body
    if result.returncode:
        raise RuntimeError(f"gh api {path}: {result.stderr.strip()[:200]}")
    head, _, text = result.stdout.replace("\r\n", "\n").partition("\n\n")
    body = json.loads(text) if text.strip() else {}
    tags = [line.split(":", 1)[1].strip() for line in head.splitlines() if line.lower().startswith("etag:")]
    if tags:
        ETAGS[path] = (tags[0], body)
    return body


# Runs seen without a job that asks for the repository's label are not read again, which keeps the
# calls to a repository at one a poll. shortcut: a job added to a run later is missed; restart to reset.
NOT_OURS = set()


def repo_jobs(repo, label):
    """Jobs of the repository that ask for its label, from its queued and running runs."""
    found = []
    for run in gh_cached(f"repos/{repo}/actions/runs?per_page=30")["workflow_runs"]:
        if run["status"] not in ("queued", "in_progress") or run["id"] in NOT_OURS:
            continue
        jobs = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
        # A missing head repository (a deleted fork) counts as a fork.
        fork = (run.get("head_repository") or {}).get("full_name", "").lower() != repo.lower()
        ours = [
            {**job, "repo": repo, "event": run.get("event"), "fork": fork}
            for job in jobs if label in job.get("labels", [])
        ]
        if not ours:
            NOT_OURS.add(run["id"])
        found += ours
    return found


def all_jobs(config):
    found = []
    for entry in config["repos"]:
        try:
            found += repo_jobs(entry["repo"], entry["label"])
        except RuntimeError as error:
            print(f"{entry['repo']}: {error}", file=sys.stderr)
    return found


def start_container(url, token, name, jit):
    request = urllib.request.Request(
        f"{url}/start?id={name}",
        data=json.dumps({"jit": jit}).encode(),
        # Cloudflare refuses the default Python user agent (error 1010) on workers.dev.
        headers={"authorization": f"Bearer {token}", "content-type": "application/json", "user-agent": "crewship-cf-runner"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT):
        pass


def register_runner(repo, label, name):
    """One single-use JIT runner for a job; its config is in `encoded_jit_config`."""
    return gh(
        f"repos/{repo}/actions/runners/generate-jitconfig",
        payload={"name": name, "runner_group_id": 1, "labels": [*BASE_LABELS, label], "work_folder": "_work"},
    )


def delete_runner(repo, runner_id):
    try:
        gh("--method", "DELETE", f"repos/{repo}/actions/runners/{runner_id}")
    except RuntimeError:
        pass


def dispatch_job(repo, label, job_id, url, token):
    """Register one JIT runner and start its container; delete the runner when the start fails."""
    name = f"cf-{job_id}"
    made = register_runner(repo, label, name)
    last = None
    for _ in range(START_ATTEMPTS):
        try:
            start_container(url, token, name, made["encoded_jit_config"])
            return made["runner"]["id"]
        except (urllib.error.URLError, TimeoutError) as error:
            last = error
            time.sleep(5)
    delete_runner(repo, made["runner"]["id"])
    raise RuntimeError(f"container start for {name} failed: {last}")


def kvz_name(job_id, tries):
    return f"kvz-{job_id}-{tries}"


def kvz_kubectl(kvz, *args, stdin=None):
    """Run `kvz kubectl` on the cluster's host over ssh; the only way this module reaches the cluster."""
    prefix = f"export PATH={shlex.quote(kvz['path'])}:$PATH; " if kvz.get("path") else ""
    command = f"{prefix}kvz kubectl {' '.join(shlex.quote(arg) for arg in args)}"
    key = ["-i", kvz["ssh_key"]] if kvz.get("ssh_key") else []
    try:
        result = subprocess.run(
            ["ssh", *key, "-o", "BatchMode=yes", kvz["ssh"], command],
            input=stdin, capture_output=True, text=True, timeout=HTTP_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"kvz kubectl {args[0]}: {error}") from error
    if result.returncode:
        raise RuntimeError(f"kvz kubectl {args[0]}: {result.stderr.strip()[:200]}")
    return result.stdout


def cluster_idle(kvz):
    """A node that may take one more job now, else None. Every error means busy, never a start."""
    try:
        snapshot = kvz_kubectl(kvz, "get", "nodes,pods,jobs", "-A", "-o", "json")
        for node in kvz["node"]:
            verdict = subprocess.run(
                [str(IDLE_CHECK), node, kvz["namespace"], str(kvz["max"]), str(kvz["cpu_pct"]), str(kvz["mem_pct"])],
                input=snapshot, capture_output=True, text=True, timeout=HTTP_TIMEOUT,
            )
            if verdict.returncode == 0:
                return node
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"kvz idle check: {error}", file=sys.stderr)
    return None


def kvz_manifest(kvz, name, jit, node):
    labels = {"app": "crewship-kvz-runner", "crewship-name": name}
    meta = {"name": name, "namespace": kvz["namespace"], "labels": labels}
    size = {"cpu": kvz["cpu"], "memory": kvz["memory"]}
    container = {
        "name": "runner", "image": kvz["image"], "command": RUNNER_COMMAND,
        "envFrom": [{"secretRef": {"name": name}}],
        "resources": {"requests": size, "limits": size},
    }
    job = {
        "backoffLimit": 0, "ttlSecondsAfterFinished": 300, "activeDeadlineSeconds": 21600,
        "template": {"metadata": {"labels": labels}, "spec": {
            "restartPolicy": "Never", "nodeSelector": {"kubernetes.io/hostname": node}, "containers": [container]}},
    }
    return {"apiVersion": "v1", "kind": "List", "items": [
        {"apiVersion": "v1", "kind": "Secret", "metadata": meta, "stringData": {"JITCONFIG": jit}},
        {"apiVersion": "batch/v1", "kind": "Job", "metadata": meta, "spec": job},
    ]}


def ensure_namespace(kvz):
    """Create our namespace when it is missing; an existing namespace is never changed."""
    try:
        kvz_kubectl(kvz, "get", "namespace", kvz["namespace"], "-o", "name")
    except RuntimeError as error:
        if "NotFound" not in str(error):
            raise
        namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": kvz["namespace"], "labels": {"app": "crewship-kvz-runner"}}}
        kvz_kubectl(kvz, "create", "-f", "-", stdin=json.dumps(namespace))


def start_cluster(kvz, name, jit, node):
    ensure_namespace(kvz)
    kvz_kubectl(kvz, "create", "-f", "-", stdin=json.dumps(kvz_manifest(kvz, name, jit, node)))


def delete_cluster_objects(kvz, name):
    kvz_kubectl(
        kvz, "-n", kvz["namespace"], "delete", "job,secret", "-l", f"crewship-name={name}",
        "--ignore-not-found", "--wait=false",
    )


def start_local(kvz, name, jit):
    """Run the same single-use runner as a throwaway container on this host."""
    command = ["docker", "run", "--rm", "-d", "--name", name, "-e", "JITCONFIG", "--entrypoint", RUNNER_COMMAND[0], kvz["image"], *RUNNER_COMMAND[1:]]
    try:
        subprocess.run(command, env={**os.environ, "JITCONFIG": jit}, check=True, capture_output=True, timeout=HTTP_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"local start for {name} failed: {error}") from error


def dispatch_kvz(entry, job, tries):
    """Register one JIT runner and start it on the cluster when the job is safe and the cluster idle, else here.

    Returns (runner id, "cluster" or "local"). A failed cluster start removes its objects and falls back
    to this host; a failed local start deletes the runner.
    """
    kvz, repo, name = entry["kvz"], entry["repo"], kvz_name(job["id"], tries)
    made = register_runner(repo, entry["label"], name)
    jit, runner = made["encoded_jit_config"], made["runner"]["id"]
    node = None if job.get("fork") or job.get("event") in KVZ_NEVER_EVENTS else cluster_idle(kvz)
    if node:
        try:
            start_cluster(kvz, name, jit, node)
            return runner, "cluster"
        except RuntimeError as error:
            print(f"{repo} job {job['id']}: {error}", file=sys.stderr)
            try:
                delete_cluster_objects(kvz, name)
            except RuntimeError:
                pass  # the next cleanup pass or the Job's own TTL removes them
    try:
        start_local(kvz, name, jit)
    except RuntimeError:
        delete_runner(repo, runner)
        raise
    return runner, "local"


def cleanup_cluster(entry, state):
    """Delete the Job and Secret of each finished cluster job, and its runner; mark the state entry cleaned."""
    kvz = entry["kvz"]
    pending = {k: v for k, v in state.items() if v.get("where") == "cluster" and v["repo"] == entry["repo"] and not v.get("cleaned")}
    if not pending:
        return
    items = json.loads(kvz_kubectl(kvz, "-n", kvz["namespace"], "get", "jobs", "-o", "json"))["items"]
    running = {
        item["metadata"]["name"] for item in items
        if not item.get("status", {}).get("completionTime")
        and not any(c["type"] == "Failed" and c["status"] == "True" for c in item.get("status", {}).get("conditions", []))
    }
    for key, value in pending.items():
        if value["name"] in running:
            continue
        delete_cluster_objects(kvz, value["name"])
        delete_runner(value["repo"], value["runner"])
        value["cleaned"] = True


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def write_state(path, state):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def poll(config, state, now=None):
    """One pass over every repository. Returns the new state."""
    now = now or time.time()
    state_dir = Path(config["state_dir"])
    entries = {entry["repo"]: entry for entry in config["repos"]}
    jobs = all_jobs(config)
    by_id = {job["id"]: job for job in jobs}
    for job_id in plan(jobs, state, now, config):
        repo = by_id[job_id]["repo"]
        entry = entries[repo]
        old = state.get(str(job_id))
        tries = (old["tries"] if old else 0) + 1
        try:
            if entry.get("kvz"):
                runner, where = dispatch_kvz(entry, by_id[job_id], tries)
            else:
                url = (state_dir / "worker-url").read_text().strip()
                token = (state_dir / "dispatch-token").read_text().strip()
                runner, where = dispatch_job(repo, entry["label"], job_id, url, token), None
        except RuntimeError as error:
            print(f"{repo} job {job_id}: {error}", file=sys.stderr)
            state[str(job_id)] = {"repo": repo, "at": now, "tries": tries, "failed": True}
            continue
        if old and old.get("runner"):
            delete_runner(repo, old["runner"])
        state[str(job_id)] = {"repo": repo, "at": now, "tries": tries, "runner": runner}
        if where:
            state[str(job_id)]["where"] = where
        if where == "cluster":
            state[str(job_id)]["name"] = kvz_name(job_id, tries)
        print(f"{repo} job {job_id}: runner started ({where or 'worker'})")
    for entry in config["repos"]:
        if entry.get("kvz"):
            try:
                cleanup_cluster(entry, state)
            except (RuntimeError, ValueError) as error:
                print(f"{entry['repo']}: cleanup: {error}", file=sys.stderr)
    return {k: v for k, v in state.items() if now - v["at"] < FORGET_SECONDS}


def in_flight(config, state):
    """Dispatched jobs that GitHub still shows queued or running."""
    # A failed listing raises: a deploy must not go ahead on a guess.
    jobs = [job for entry in config["repos"] for job in repo_jobs(entry["repo"], entry["label"])]
    live = {str(job["id"]) for job in jobs if job["status"] in ("queued", "in_progress")}
    return len(live & state.keys())


def dispatch(config, once=False):
    state_file = Path(config["state_dir"]) / "state.json"
    while True:
        state = read_state(state_file)
        write_state(state_file, poll(config, state))
        if once:
            return
        time.sleep(config["poll_seconds"])


def read_env_file(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip().removeprefix("export ")
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("'\"")
    return env


def source_hash(config):
    digest = hashlib.sha256(json.dumps({"max_instances": config["max_instances"]}).encode())
    for path in sorted(Path(config["source_dir"]).rglob("*")):
        if path.is_file() and "node_modules" not in path.parts:
            digest.update(str(path.relative_to(config["source_dir"])).encode() + path.read_bytes())
    return digest.hexdigest()


def wrangler_config(config):
    return {
        "name": WORKER,
        "main": "src/index.ts",
        "compatibility_date": "2026-11-01",
        "containers": [{
            "class_name": "Runner", "image": "./Dockerfile",
            "instance_type": INSTANCE_TYPE, "max_instances": config["max_instances"],
        }],
        "durable_objects": {"bindings": [{"class_name": "Runner", "name": "RUNNER"}]},
        "migrations": [{"new_sqlite_classes": ["Runner"], "tag": "v1"}],
    }


def account_api(path, env):
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/{path}",
        headers={"authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}"},
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as reply:
        return json.load(reply)["result"]


def deploy(config):
    if all(entry.get("kvz") for entry in config["repos"]):
        print("cf-runner: every repository uses the cluster; no Worker to deploy")
        return
    state_dir = Path(config["state_dir"])
    stamp = state_dir / "deployed"
    digest = source_hash(config)
    if stamp.exists() and stamp.read_text() == digest:
        print("cf-runner: Worker up to date")
        return
    # A deploy replaces running containers, so it waits for the jobs to end.
    busy = in_flight(config, read_state(state_dir / "state.json"))
    if busy:
        raise SystemExit(f"cf-runner: {busy} job(s) in flight; deploy again when they end")
    env = {**os.environ, **read_env_file(config["credentials_file"])}
    build = Path(config["source_dir"]).parent / "build"
    shutil.rmtree(build, ignore_errors=True)
    shutil.copytree(config["source_dir"], build)
    (build / "wrangler.jsonc").write_text(json.dumps(wrangler_config(config), indent=2))
    token_file = state_dir / "dispatch-token"
    for step in (["npm", "install", "--no-audit", "--no-fund"], ["npx", "wrangler", "deploy"]):
        subprocess.run(step, cwd=build, env=env, check=True)
    subprocess.run(
        ["npx", "wrangler", "secret", "put", "DISPATCH_TOKEN", "--name", WORKER],
        cwd=build, env=env, check=True, input=token_file.read_text().strip(), text=True,
    )
    subdomain = account_api(f"accounts/{env['CLOUDFLARE_ACCOUNT_ID']}/workers/subdomain", env)["subdomain"]
    (state_dir / "worker-url").write_text(f"https://{WORKER}.{subdomain}.workers.dev\n")
    stamp.write_text(digest)
    print("cf-runner: Worker deployed")


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    if command == "dispatch":
        dispatch(load_config(), once="--once" in argv)
    elif command == "deploy":
        deploy(load_config())
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
