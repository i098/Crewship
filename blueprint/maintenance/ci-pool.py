#!/usr/bin/env python3
"""CI pool: just-in-time GitHub Actions runners, one job per fresh container.

  ci-pool.py apply [--check]   crewship.ci_pool as JSON on stdin; sizes the pool,
                               writes ci-runner@.service and enables one instance
                               per slot, and stops and cleans removed slots.
  ci-pool.py run <instance>    ExecStart of ci-runner@<instance>.service: asks
                               GitHub for a JIT runner, runs one job in a fresh
                               container from the official runner image, exits.

GitHub removes a JIT runner after its one job, so nothing is registered or
deregistered by hand. docs/ci-pool.md has the operator guide.
"""

import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IMAGE = "ghcr.io/actions/actions-runner:latest"
DEFAULTS = {"total_slots": "auto", "job_cpus": 4, "job_memory_gb": 8}
# The auto size takes this share of the host's CPUs and memory.
SHARE = 0.5
# A failed GitHub call or container start waits this long before systemd's
# restart, so a broken slot costs at most two API calls a minute.
FAILURE_PAUSE_SECONDS = 60
# The runner image's run.sh exits 0 even when the listener fails, so a
# container that ends sooner than this did not run a job.
MIN_JOB_SECONDS = 30
HOME = Path.home()
CONFIG = HOME / ".config/ci-pool/pool.json"
UNITS = HOME / ".config/systemd/user"
TEMPLATE = UNITS / "ci-runner@.service"
WANTS = UNITS / "default.target.wants"
HOOK = HOME / ".config/ci-pool/job-started.sh"
HOOK_ENV = "ACTIONS_RUNNER_HOOK_JOB_STARTED"
UNIT_TEXT = """\
# Written by ci-pool.py apply (Crewship); instances come from crewship.ci_pool.
[Unit]
Description=CI pool runner slot %i (one GitHub Actions job per start)
After=network-online.target
StartLimitIntervalSec=0

[Service]
ExecStart=/usr/bin/python3 %h/.local/bin/ci-pool.py run %i
Environment=PATH=%h/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Restart=always
RestartSec=5
TimeoutStopSec=90
# 143 is a slot stopped by systemctl (SIGTERM): inactive, not failed.
SuccessExitStatus=143

[Install]
WantedBy=default.target
"""
# Runs as the image's `runner` user, which has passwordless sudo: empty the
# slot's work directory, give the runner the bind mounts, then run one job.
CONTAINER_PREP = (
    "sudo find /home/runner/_work -mindepth 1 -delete"
    " && sudo chown runner:runner /home/runner/_work /opt/hostedtoolcache /home/runner/.cache"
    " && exec /home/runner/run.sh"
)
# The runner's job-started hook (ACTIONS_RUNNER_HOOK_JOB_STARTED) runs before
# any step. Only the repository's own code runs on the host: for a fork's pull
# request the hook kills every process in the container, because a failed hook
# alone would still let later `if: always()` steps run.
HOOK_TEXT = """\
#!/usr/bin/env bash
# Written by ci-pool.py apply (Crewship): refuse code from outside the repository.
python3 - <<'PY' || { sudo kill -KILL -1; exit 1; }
import json, os, sys
repo = os.environ["GITHUB_REPOSITORY"]
with open(os.environ["GITHUB_EVENT_PATH"]) as f:
    event = json.load(f)
heads = []
if "pull_request" in event:
    heads.append(((event["pull_request"].get("head") or {}).get("repo") or {}).get("full_name"))
if "workflow_run" in event:
    heads.append((event["workflow_run"].get("head_repository") or {}).get("full_name"))
for head in heads:
    if head != repo:
        sys.exit(f"ci-pool: refused, the code comes from {head or 'a deleted fork'}, not {repo}")
PY
"""


def slug(repo):
    return re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")


def totals():
    """CPUs and MemTotal in GiB."""
    meminfo = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return len(os.sched_getaffinity(0)), int(meminfo["MemTotal"].split()[0]) / 1024**2


def auto_slots(pool, cpus, memory_gib):
    return math.floor(min(cpus * SHARE / pool["job_cpus"], memory_gib * SHARE / pool["job_memory_gb"]))


def wanted_slots(pool, total):
    """Instance names in config order, cut to `total` slots."""
    names = [
        f"{slug(entry['repo'])}-{n}" for entry in pool["repos"] for n in range(1, entry["slots"] + 1)
    ]
    if len(names) > total:
        print(
            f"WARNING: {len(names)} slots configured, pool total is {total}; "
            f"not starting {', '.join(names[total:])}",
            file=sys.stderr,
        )
    return names[:total]


def docker():
    # Docker group membership is opt-in (tasks/docker.yml); without it use sudo.
    return ["docker"] if os.access("/var/run/docker.sock", os.W_OK) else ["sudo", "-n", "docker"]


def quiet(argv):
    return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def busy(name):
    """True while the slot's container runs a job; unknown counts as busy."""
    result = subprocess.run([*docker(), "top", f"ci-runner-{name}", "-eo", "pid,comm"],
                            capture_output=True, text=True)
    return "Runner.Worker" in result.stdout or (
        result.returncode != 0 and "No such container" not in result.stderr
    )


def remove_tree(path):
    # Job files belong to the container's runner uid, so delete as root inside
    # the runner image rather than needing sudo rights on the host path.
    subprocess.run([*docker(), "run", "--rm", "--user", "0", "--volume", f"{path}:/w",
                    "--entrypoint", "find", IMAGE, "/w", "-mindepth", "1", "-delete"],
                   check=True, stdout=subprocess.DEVNULL)
    path.rmdir()


def systemctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def apply(check):
    pool = {**DEFAULTS, **json.load(sys.stdin)}
    have = sorted(p.name[len("ci-runner@"):-len(".service")] for p in WANTS.glob("ci-runner@*.service"))
    # The pool deletes only below this directory, which it alone creates.
    root = Path(pool["data_dir"]) / "ci-pool"
    total = pool["total_slots"]
    if total == "auto":
        total = auto_slots(pool, *totals())
    want = wanted_slots(pool, total)
    keep_caches = {slug(entry["repo"]) for entry in pool["repos"]}
    changes = []

    def write(path, text):
        if path.exists() and path.read_text() == text:
            return False
        changes.append(f"write {path}")
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return True

    config = json.dumps(pool, indent=2, sort_keys=True) + "\n"
    reconfigured = not CONFIG.exists() or CONFIG.read_text() != config
    if reconfigured:
        changes.append(f"write {CONFIG}")
    write(HOOK, HOOK_TEXT)
    if write(TEMPLATE, UNIT_TEXT) and not check:
        systemctl("daemon-reload")
    for name in sorted(set(have) - set(want)):
        unit = f"ci-runner@{name}.service"
        if busy(name):
            # Not stopped: the slot leaves after its current job (see run).
            changes.append(f"drain {unit}")
            if not check:
                systemctl("disable", unit)
        else:
            changes.append(f"stop {unit}")
            if not check:
                systemctl("disable", "--now", unit)
    stale, held = [], set()
    for path in sorted((root / "work").glob("*")):
        if path.name in want:
            continue
        if busy(path.name):
            held.add(path.name.rpartition("-")[0])
        else:
            stale.append(path)
    stale += [p for p in sorted((root / "cache").glob("*")) if p.name not in keep_caches | held]
    for path in stale:
        changes.append(f"remove {path}")
        if not check:
            remove_tree(path)
    if reconfigured and not check:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(config)
    for name in want:
        unit = f"ci-runner@{name}.service"
        if name not in have:
            changes.append(f"start {unit}")
            if not check:
                systemctl("enable", "--now", unit)
        elif reconfigured and not busy(name):
            # A busy slot reads the new config when its next job starts.
            changes.append(f"restart {unit}")
            if not check:
                systemctl("restart", unit)
    if changes:
        print("\n".join(changes))
    print(f"pool: {len(want)} of {total} slots", file=sys.stderr)
    return 0


def run(instance):
    unit = f"ci-runner@{instance}.service"
    if quiet(["systemctl", "--user", "--quiet", "is-enabled", unit]):
        # Drained by apply while it held a job: that job is done, leave for good.
        systemctl("stop", unit)
        return 0
    pool = json.loads(CONFIG.read_text())
    base = instance.rpartition("-")[0]
    entry = next((e for e in pool["repos"] if slug(e["repo"]) == base), None)
    if entry is None:
        print(f"{instance}: no repository in {CONFIG}; run ci-pool.py apply", file=sys.stderr)
        time.sleep(FAILURE_PAUSE_SECONDS)
        return 1
    repo = entry["repo"]
    root = Path(pool["data_dir"]) / "ci-pool"
    work, cache = root / "work" / instance, root / "cache" / base
    for path in (work, cache / "tool", cache / "home"):
        path.mkdir(parents=True, exist_ok=True)

    body = {
        "name": f"pool-{instance}-{int(time.time())}",
        "runner_group_id": 1,
        "labels": ["self-hosted", *entry["labels"]],
        "work_folder": "_work",
    }
    # The host's own gh login, read at run time; no token is stored.
    result = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/actions/runners/generate-jitconfig", "--input", "-"],
        input=json.dumps(body), capture_output=True, text=True,
    )
    if result.returncode:
        print(f"{instance}: generate-jitconfig failed: {result.stderr.strip()}", file=sys.stderr)
        time.sleep(FAILURE_PAUSE_SECONDS)
        return 1
    jit = json.loads(result.stdout)
    print(f"{instance}: runner {body['name']} (id {jit['runner']['id']}) for {repo}", flush=True)

    # systemctl stop: unwind through `finally` so the container goes too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    container, rc, started = f"ci-runner-{instance}", 1, time.monotonic()
    try:
        quiet([*docker(), "rm", "--force", container])
        # The single-use JIT config travels in a 0600 env file, never in argv.
        with tempfile.NamedTemporaryFile("w", dir=os.environ.get("XDG_RUNTIME_DIR")) as env:
            env.write(f"ACTIONS_RUNNER_INPUT_JITCONFIG={jit['encoded_jit_config']}\n")
            env.flush()
            subprocess.run([
                *docker(), "create", "--init", "--pull", "always", "--rm", "--name", container,
                "--label", f"crewship.ci-pool={instance}",
                "--cpus", str(pool["job_cpus"]),
                "--memory", f"{pool['job_memory_gb']}g", "--memory-swap", f"{pool['job_memory_gb']}g",
                "--pids-limit", "8192",
                "--env-file", env.name,
                "--env", "RUNNER_TOOL_CACHE=/opt/hostedtoolcache",
                # Set on GitHub-hosted runners; tools such as Ansible read it.
                "--env", "USER=runner",
                "--volume", f"{work}:/home/runner/_work",
                "--volume", f"{cache / 'tool'}:/opt/hostedtoolcache",
                "--volume", f"{cache / 'home'}:/home/runner/.cache",
                # --mount, not --volume: a missing hook fails the create instead of
                # becoming an empty directory, so no job runs without the check.
                "--mount", f"type=bind,src={HOOK},dst=/home/runner/job-started.sh,readonly",
                "--env", f"{HOOK_ENV}=/home/runner/job-started.sh",
                IMAGE, "bash", "-c", CONTAINER_PREP,
            ], check=True, stdout=subprocess.DEVNULL)
        rc = subprocess.run([*docker(), "start", "--attach", container]).returncode
    except Exception as error:
        print(f"{instance}: container start failed: {error}", file=sys.stderr)
    finally:
        quiet([*docker(), "rm", "--force", container])
        # GitHub already removed a runner that finished a job, so this is then a harmless 404.
        quiet(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/runners/{jit['runner']['id']}"])
    if not rc and time.monotonic() - started < MIN_JOB_SECONDS:
        rc = 1
    if rc:
        time.sleep(FAILURE_PAUSE_SECONDS)
    return rc


def main(argv):
    if argv[:1] == ["apply"] and argv[1:] in ([], ["--check"]):
        return apply(check=argv[1:] == ["--check"])
    if argv[:1] == ["run"] and len(argv) == 2:
        return run(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
