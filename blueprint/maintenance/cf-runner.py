#!/usr/bin/env python3
"""Cloudflare container runner: one fresh Cloudflare Container for each GitHub Actions job.

  cf-runner.py dispatch [--once]   run by cf-runner-dispatch.service: polls the configured
                                   repositories for queued jobs that ask for a repository's
                                   label, mints one JIT runner for each and starts one container.
  cf-runner.py deploy              builds and deploys the Worker and its container image when
                                   the source or config changed; refuses while a job is in flight.

The GitHub token never leaves the host (`gh` login); only the JIT runner config goes to the
Worker. GitHub removes a JIT runner after its one job. docs/cloudflare-runner.md is the guide.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("CF_RUNNER_CONFIG", HOME / ".config/cf-runner/config.json"))
DEFAULTS = {
    "worker": "crewship-cf-runner",
    "instance_type": "standard-4",
    "max_instances": 4,
    "poll_seconds": 20,
    "retry_after_seconds": 900,
    "max_tries": 3,
}
# A job that finished long ago is no longer interesting; its state entry goes after this.
FORGET_SECONDS = 86400
START_ATTEMPTS = 2
HTTP_TIMEOUT = 60
BASE_LABELS = ["self-hosted", "linux"]


def load_config(path=CONFIG):
    config = {**DEFAULTS, **json.loads(Path(path).read_text())}
    config.setdefault("state_dir", str(HOME / ".local/state/cf-runner"))
    config.setdefault("source_dir", str(HOME / ".local/share/cf-runner/src"))
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


def gh(*args, payload=None):
    result = subprocess.run(
        ["gh", "api", *args] + (["--input", "-"] if payload is not None else []),
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=HTTP_TIMEOUT,
    )
    if result.returncode:
        raise RuntimeError(f"gh api {args[-1]}: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


# Runs seen without a job that asks for the repository's label are not read again, which keeps the
# calls to a repository at one a poll. shortcut: a job added to a run later is missed; restart to reset.
NOT_OURS = set()


def repo_jobs(repo, label):
    """Jobs of the repository that ask for its label, from its queued and running runs."""
    found = []
    for run in gh(f"repos/{repo}/actions/runs?per_page=30")["workflow_runs"]:
        if run["status"] not in ("queued", "in_progress") or run["id"] in NOT_OURS:
            continue
        jobs = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
        ours = [{**job, "repo": repo} for job in jobs if label in job.get("labels", [])]
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
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT):
        pass


def dispatch_job(repo, label, job_id, url, token):
    """Register one JIT runner and start its container; delete the runner when the start fails."""
    name = f"cf-{job_id}"
    made = gh(
        f"repos/{repo}/actions/runners/generate-jitconfig",
        payload={
            "name": name,
            "runner_group_id": 1,
            "labels": [*BASE_LABELS, label],
            "work_folder": "_work",
        },
    )
    last = None
    for _ in range(START_ATTEMPTS):
        try:
            start_container(url, token, name, made["encoded_jit_config"])
            return made["runner"]["id"]
        except (urllib.error.URLError, TimeoutError) as error:
            last = error
            time.sleep(5)
    try:
        gh("--method", "DELETE", f"repos/{repo}/actions/runners/{made['runner']['id']}")
    except RuntimeError:
        pass
    raise RuntimeError(f"container start for {name} failed: {last}")


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
    url = (state_dir / "worker-url").read_text().strip()
    token = (state_dir / "dispatch-token").read_text().strip()
    labels = {entry["repo"]: entry["label"] for entry in config["repos"]}
    jobs = all_jobs(config)
    by_id = {job["id"]: job for job in jobs}
    for job_id in plan(jobs, state, now, config):
        repo = by_id[job_id]["repo"]
        old = state.get(str(job_id))
        tries = (old["tries"] if old else 0) + 1
        try:
            runner = dispatch_job(repo, labels[repo], job_id, url, token)
        except RuntimeError as error:
            print(f"{repo} job {job_id}: {error}", file=sys.stderr)
            state[str(job_id)] = {"repo": repo, "at": now, "tries": tries, "failed": True}
            continue
        if old and old.get("runner"):
            try:
                gh("--method", "DELETE", f"repos/{repo}/actions/runners/{old['runner']}")
            except RuntimeError:
                pass
        state[str(job_id)] = {"repo": repo, "at": now, "tries": tries, "runner": runner}
        print(f"{repo} job {job_id}: runner cf-{job_id} started")
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
    digest = hashlib.sha256(json.dumps({k: config[k] for k in ("worker", "instance_type", "max_instances")}).encode())
    for path in sorted(Path(config["source_dir"]).rglob("*")):
        if path.is_file() and "node_modules" not in path.parts:
            digest.update(str(path.relative_to(config["source_dir"])).encode() + path.read_bytes())
    return digest.hexdigest()


def wrangler_config(config):
    return {
        "name": config["worker"],
        "main": "src/index.ts",
        "compatibility_date": "2026-11-01",
        "containers": [{
            "class_name": "Runner", "image": "./Dockerfile",
            "instance_type": config["instance_type"], "max_instances": config["max_instances"],
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
        ["npx", "wrangler", "secret", "put", "DISPATCH_TOKEN", "--name", config["worker"]],
        cwd=build, env=env, check=True, input=token_file.read_text().strip(), text=True,
    )
    subdomain = account_api(f"accounts/{env['CLOUDFLARE_ACCOUNT_ID']}/workers/subdomain", env)["subdomain"]
    (state_dir / "worker-url").write_text(f"https://{config['worker']}.{subdomain}.workers.dev\n")
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
