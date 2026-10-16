#!/usr/bin/env python3
"""CI pool: just-in-time GitHub Actions runners, one job per fresh container.

  ci-pool.py apply [--check]   crewship.ci_pool as JSON on stdin; sizes the pool,
                               writes ci-runner@.service and enables one instance
                               per slot, and stops and cleans removed slots.
  ci-pool.py watch [--dry-run] run by ci-pool-watch.timer every minute: restarts a
                               slot that GitHub shows offline and that has no
                               container; --dry-run only prints what it would do.
  ci-pool.py image             run by ci-pool-image.timer: builds the pool's job
                               image (see DOCKERFILE) from the latest official one.
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
# The image every job container starts from. This default is built on the host by
# `ci-pool.py image` from IMAGE plus the packages the jobs would otherwise install
# on every start; any other name is pulled as it is.
BUILT_IMAGE = "crewship-ci-runner:latest"
DEFAULTS = {"total_slots": "auto", "job_cpus": 4, "job_memory_gb": 8, "image": BUILT_IMAGE}
# The auto size takes this share of the host's CPUs and memory.
SHARE = 0.5
# A failed GitHub call or container start waits this long before systemd's
# restart, so a broken slot costs at most two API calls a minute.
FAILURE_PAUSE_SECONDS = 60
# The runner image's run.sh exits 0 even when the listener fails, so a
# container that ends sooner than this did not run a job.
MIN_JOB_SECONDS = 30
# `docker create` and `docker pull` wait this long (CI_POOL_DOCKER_TIMEOUT overrides it):
# on a loaded host the daemon can stall a call forever, which left a registered
# runner offline with no container. A timeout fails the slot and systemd restarts it.
DOCKER_TIMEOUT = int(os.environ.get("CI_POOL_DOCKER_TIMEOUT", 600))
# `watch` acts on a slot only after it has run this long, and then only when GitHub shows
# its runner offline and the daemon lists no container for it in two successful reads at
# least MISSING_SECONDS apart. A busy daemon answers slowly or partly; waiting is cheap.
STALL_SECONDS = 300
MISSING_SECONDS = 120
# One `watch` call to docker, systemd, or GitHub ends after this long, so a
# stalled daemon cannot hold the check that exists to find it.
WATCH_TIMEOUT = 60
# `watch` restarts at most this many slots in one run.
MAX_RESTARTS = 2
# A slot's container gets this long to stop before docker kills it.
STOP_GRACE_SECONDS = 60
# An image build installs packages on a loaded host.
BUILD_TIMEOUT = 3600
HOME = Path.home()
CONFIG = HOME / ".config/ci-pool/pool.json"
UNITS = HOME / ".config/systemd/user"
TEMPLATE = UNITS / "ci-runner@.service"
WANTS = UNITS / "default.target.wants"
WATCH_SERVICE = UNITS / "ci-pool-watch.service"
WATCH_TIMER = UNITS / "ci-pool-watch.timer"
WATCH_STATE = HOME / ".config/ci-pool/watch-state.json"
IMAGE_SERVICE = UNITS / "ci-pool-image.service"
IMAGE_TIMER = UNITS / "ci-pool-image.timer"
HOOK = HOME / ".config/ci-pool/job-started.sh"
# The containerd image store keeps a container's own writes on the system disk, so these
# paths take the heavy ones to the data disk. Scratch is wiped when a job starts; the apt
# packages and lists stay (and are per slot, because apt locks its archive directory).
SCRATCH_DIRS = {"tmp": "/tmp", "postgresql": "/var/lib/postgresql", "bun": "/home/runner/.bun"}
APT_DIRS = {"archives": "/var/cache/apt/archives", "lists": "/var/lib/apt/lists"}
# Subdirectories of a repository's cache directory <data_dir>/ci-pool/cache/<owner>-<name>/.
CACHE_DIRS = ("tool", "home", "cargo-registry", "cargo-git")
# A repository entry with "docker": "dind" gets a Docker daemon of its own in each slot: a
# rootless dockerd in a sidecar container on a network of the slot, never the host's socket.
# The image still needs --privileged (for its user namespace and mounts); the job's code
# reaches only the daemon, which runs as the image's non-root `rootless` user (DIND_UID).
DIND_IMAGE = "docker:dind-rootless"
DIND_UID = 1000
# The job shares the sidecar's network namespace, so the daemon and every port that a
# `docker compose` service publishes are on the job's localhost.
DIND_ENV = {"DOCKER_HOST": "tcp://localhost:2376", "DOCKER_TLS_VERIFY": "1", "DOCKER_CERT_PATH": "/certs/client"}
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
# SIGTERM reaches only `run`, which stops its container (60 s grace) and waits for the
# removal; whatever is left in the cgroup after TimeoutStopSec is killed.
KillMode=mixed
TimeoutStopSec=300
# 143 is a slot stopped by systemctl (SIGTERM): inactive, not failed.
SuccessExitStatus=143

[Install]
WantedBy=default.target
"""
WATCH_SERVICE_TEXT = """\
# Written by ci-pool.py apply (Crewship).
[Unit]
Description=CI pool watch: restart stalled slots

[Service]
Type=oneshot
TimeoutStartSec=300
ExecStart=/usr/bin/python3 %h/.local/bin/ci-pool.py watch
Environment=PATH=%h/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
"""
WATCH_TIMER_TEXT = """\
# Written by ci-pool.py apply (Crewship).
[Unit]
Description=CI pool watch every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
"""
IMAGE_SERVICE_TEXT = """\
# Written by ci-pool.py apply (Crewship).
[Unit]
Description=CI pool runner image: rebuild from the latest official runner image

[Service]
Type=oneshot
Nice=10
ExecStart=/usr/bin/python3 %h/.local/bin/ci-pool.py image
Environment=PATH=%h/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
"""
IMAGE_TIMER_TEXT = """\
# Written by ci-pool.py apply (Crewship).
[Unit]
Description=CI pool runner image every hour

[Timer]
OnBootSec=1min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
"""
# The packages the jobs of the pool's repositories install on every start: a
# compiler, the GTK runtime, the codex-gpui Rust/GUI build libraries, Postgres 17 and 18 with pgvector (from the PostgreSQL apt repository),
# and bun. REFRESH changes daily, so apt and bun update once a day; the layers
# before it stay cached. The apt archive is kept so a job's own `apt-get install`
# can read the packages from a cache mount.
DOCKERFILE = f"""\
FROM {IMAGE}
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN rm -f /etc/apt/apt.conf.d/docker-clean
ARG REFRESH
RUN apt-get update -qq \\
 && apt-get install -y -qq --no-install-recommends \\
      build-essential pkg-config libgtk-3-0 unzip git curl ca-certificates gnupg lsb-release postgresql-common \\
      clang cmake libssl-dev libzstd-dev libfontconfig-dev libfreetype-dev libasound2-dev \\
      libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libx11-xcb-dev libxcb1-dev libvulkan-dev \\
 && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \\
 && apt-get install -y -qq --no-install-recommends postgresql-17 postgresql-client-17 postgresql-18 postgresql-client-18 postgresql-18-pgvector \\
 && curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash
# Jobs mount their own directory over /var/lib/postgresql (see CONTAINER_PREP), so the
# clusters that the packages created are kept here and copied in when a job starts.
# Only the newest installed package creates its main cluster, so create the 17 one when it is
# missing. Each cluster starts on port 5432, so stop both and start neither at boot: a job
# starts the version it needs (see docs/ci-pool.md).
RUN [ -d /etc/postgresql/17/main ] || (pg_createcluster 17 main && pg_conftool 17 main set port 5432) \
 && for v in 17 18; do pg_ctlcluster $v main stop 2>/dev/null || true; echo manual > /etc/postgresql/$v/main/start.conf; done \
 && cp -a /var/lib/postgresql /opt/postgresql-seed
# The compose plugin, for repositories whose jobs talk to their own daemon (DIND_IMAGE).
COPY --from={DIND_IMAGE} /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/
USER runner
"""
# Runs as the image's `runner` user, which has passwordless sudo: empty the
# slot's work directory, give the runner the bind mounts, then run one job.
CONTAINER_PREP = (
    "sudo find /home/runner/_work -mindepth 1 -delete"
    # The pool's image keeps a fresh Postgres cluster here; other images have none.
    " && if [ -d /opt/postgresql-seed ]; then"
    " sudo cp -a /opt/postgresql-seed/. /var/lib/postgresql/ && sudo chown postgres:postgres /var/lib/postgresql; fi"
    " && sudo chown runner:runner /home/runner/_work /opt/hostedtoolcache /home/runner/.cache"
    " /home/runner/.cargo /home/runner/.cargo/registry /home/runner/.cargo/git"
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


def bounded(argv, seconds=None):
    """Prefix argv with coreutils `timeout`: TERM after `seconds` (default DOCKER_TIMEOUT; sudo
    relays it to docker, which SIGKILL from Python would not reach), KILL 10 s later. A timeout exits 124."""
    return ["timeout", "--kill-after=10", str(seconds or DOCKER_TIMEOUT), *argv]


def quiet(argv):
    return subprocess.run(bounded(argv), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def busy(name):
    """True while the slot's container runs a job; unknown counts as busy. A container that
    does not exist or is not running (created, exited, dead) runs no job."""
    result = subprocess.run(bounded([*docker(), "top", f"ci-runner-{name}", "-eo", "pid,comm"]),
                            capture_output=True, text=True)
    return "Runner.Worker" in result.stdout or (
        result.returncode != 0 and not any(text in result.stderr for text in ("No such container", "is not running"))
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
    # A list, not `or`: every file is written even when the first one changed.
    units = [(TEMPLATE, UNIT_TEXT), (WATCH_SERVICE, WATCH_SERVICE_TEXT), (WATCH_TIMER, WATCH_TIMER_TEXT),
             (IMAGE_SERVICE, IMAGE_SERVICE_TEXT), (IMAGE_TIMER, IMAGE_TIMER_TEXT)]
    if any([write(path, text) for path, text in units]) and not check:
        systemctl("daemon-reload")
    for timer in (WATCH_TIMER, IMAGE_TIMER):
        if quiet(["systemctl", "--user", "--quiet", "is-enabled", timer.name]):
            changes.append(f"start {timer.name}")
            if not check:
                systemctl("enable", "--now", timer.name)
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
    for path in [*sorted((root / "work").glob("*")), *sorted((root / "scratch").glob("*")),
                 *sorted((root / "apt").glob("*")), *sorted((root / "dind").glob("*"))]:
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


def job_image(pool):
    """The configured image; the official one while the built image does not exist yet."""
    if pool["image"] == BUILT_IMAGE and quiet([*docker(), "image", "inspect", BUILT_IMAGE]):
        return IMAGE
    return pool["image"]


def refresh_image():
    """Build the pool's image from the latest official one, or pull a custom image."""
    image = {**DEFAULTS, **json.loads(CONFIG.read_text())}["image"]
    if image != BUILT_IMAGE:
        argv, stdin = [*docker(), "pull", "--quiet", image], None
        seconds = DOCKER_TIMEOUT
    else:
        argv = [*docker(), "build", "--pull", "--quiet", "--build-arg", f"REFRESH={time.strftime('%Y-%m-%d')}",
                "--tag", BUILT_IMAGE, "-"]
        stdin, seconds = DOCKERFILE, BUILD_TIMEOUT
    done = subprocess.run(bounded(argv, seconds), input=stdin, text=True, stdout=subprocess.DEVNULL)
    print(f"image {image}: exit {done.returncode}", flush=True)
    if not done.returncode:
        # Untagged layers of the previous build; images that containers use stay.
        quiet([*docker(), "image", "prune", "--force"])
    return done.returncode


def env_args(env):
    return [arg for key, value in env.items() for arg in ("--env", f"{key}={value}")]


def start_dind(instance, limits, path):
    """Start the slot's own Docker daemon in a fresh sidecar on its own network, with its data
    and TLS certificates in `path`, and return once it answers the way the job will call it."""
    name = f"ci-dind-{instance}"
    if not clear_container(name):
        raise RuntimeError("the previous Docker sidecar is still listed after its removal")
    # The previous daemon's files belong to its user namespace's uids, hence sudo.
    quiet(["sudo", "-n", "rm", "-rf", "--one-file-system", str(path)])
    path.mkdir(parents=True)
    quiet(["sudo", "-n", "install", "-d", "-o", str(DIND_UID), "-g", str(DIND_UID),
           str(path / "data"), str(path / "certs")])
    quiet([*docker(), "network", "rm", name])
    subprocess.run(bounded([*docker(), "network", "create", name]), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(bounded([
        *docker(), "run", "--detach", "--rm", "--pull", "missing", "--name", name,
        "--label", f"crewship.ci-pool={instance}", "--network", name, "--privileged", *limits,
        "--volume", f"{path / 'data'}:/home/rootless/.local/share/docker",
        "--volume", f"{path / 'certs'}:/certs",
        DIND_IMAGE,
    ]), check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + DOCKER_TIMEOUT
    while quiet([*docker(), "exec", *env_args(DIND_ENV), name, "docker", "version"]):
        if time.monotonic() > deadline:
            raise RuntimeError("the slot's Docker daemon did not answer")
        time.sleep(5)


def run(instance):
    unit = f"ci-runner@{instance}.service"
    if quiet(["systemctl", "--user", "--quiet", "is-enabled", unit]):
        # Drained by apply while it held a job: that job is done, leave for good.
        systemctl("stop", unit)
        return 0
    pool = {**DEFAULTS, **json.loads(CONFIG.read_text())}
    base = instance.rpartition("-")[0]
    entry = next((e for e in pool["repos"] if slug(e["repo"]) == base), None)
    if entry is None:
        print(f"{instance}: no repository in {CONFIG}; run ci-pool.py apply", file=sys.stderr)
        time.sleep(FAILURE_PAUSE_SECONDS)
        return 1
    repo = entry["repo"]
    root = Path(pool["data_dir"]) / "ci-pool"
    work, cache = root / "work" / instance, root / "cache" / base
    scratch, apt = root / "scratch" / instance, root / "apt" / instance
    # The previous job's files belong to other uids inside the container, hence sudo.
    quiet(["sudo", "-n", "rm", "-rf", "--one-file-system", str(scratch)])
    for name in SCRATCH_DIRS:
        (scratch / name).mkdir(parents=True, exist_ok=True)
        (scratch / name).chmod(0o1777)
    for path in (work, *(apt / name for name in APT_DIRS), *(cache / name for name in CACHE_DIRS)):
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
    container, rc, started, ours = f"ci-runner-{instance}", 1, time.monotonic(), False
    sidecar, dind = f"ci-dind-{instance}", root / "dind" / instance
    limits = ["--cpus", str(pool["job_cpus"]),
              "--memory", f"{pool['job_memory_gb']}g", "--memory-swap", f"{pool['job_memory_gb']}g",
              "--pids-limit", "8192"]
    own_docker = entry.get("docker") == "dind"
    try:
        claim_container(container)
        ours = True
        if own_docker:
            start_dind(instance, limits, dind)
        # The single-use JIT config travels in a 0600 env file, never in argv.
        with tempfile.NamedTemporaryFile("w", dir=os.environ.get("XDG_RUNTIME_DIR")) as env:
            env.write(f"ACTIONS_RUNNER_INPUT_JITCONFIG={jit['encoded_jit_config']}\n")
            env.flush()
            subprocess.run(bounded([
                *docker(), "create", "--init", "--pull", "missing", "--rm", "--name", container,
                "--label", f"crewship.ci-pool={instance}",
                *limits,
                "--env-file", env.name,
                "--env", "RUNNER_TOOL_CACHE=/opt/hostedtoolcache",
                # Set on GitHub-hosted runners; tools such as Ansible read it.
                "--env", "USER=runner",
                "--volume", f"{work}:/home/runner/_work",
                "--volume", f"{cache / 'tool'}:/opt/hostedtoolcache",
                "--volume", f"{cache / 'home'}:/home/runner/.cache",
                "--volume", f"{cache / 'cargo-registry'}:/home/runner/.cargo/registry",
                "--volume", f"{cache / 'cargo-git'}:/home/runner/.cargo/git",
                *(arg for base, dirs in ((scratch, SCRATCH_DIRS), (apt, APT_DIRS))
                  for name, target in dirs.items() for arg in ("--volume", f"{base / name}:{target}")),
                # Package managers that keep their cache outside ~/.cache.
                "--env", "BUN_INSTALL_CACHE_DIR=/home/runner/.cache/bun",
                "--env", "npm_config_cache=/home/runner/.cache/npm",
                "--env", "npm_config_store_dir=/home/runner/.cache/pnpm-store",
                # Never the host's socket: the slot's own daemon, and only its client certificate.
                *(["--network", f"container:{sidecar}", "--volume", f"{dind / 'certs/client'}:/certs/client:ro",
                   *env_args(DIND_ENV)] if own_docker else []),
                # --mount, not --volume: a missing hook fails the create instead of
                # becoming an empty directory, so no job runs without the check.
                "--mount", f"type=bind,src={HOOK},dst=/home/runner/job-started.sh,readonly",
                "--env", f"{HOOK_ENV}=/home/runner/job-started.sh",
                job_image(pool), "bash", "-c", CONTAINER_PREP,
            ]), check=True, stdout=subprocess.DEVNULL)
        rc = subprocess.run([*docker(), "start", "--attach", container]).returncode
    except Exception as error:
        print(f"{instance}: container start failed: {error}", file=sys.stderr)
    finally:
        if ours:  # never the containers of a previous start that still runs a job
            clear_container(container)
            if own_docker:
                clear_container(sidecar)
                quiet([*docker(), "network", "rm", sidecar])
        # GitHub already removed a runner that finished a job, so this is then a harmless 404.
        quiet(["gh", "api", "--method", "DELETE", f"repos/{repo}/actions/runners/{jit['runner']['id']}"])
    if not rc and time.monotonic() - started < MIN_JOB_SECONDS:
        rc = 1
    if rc:
        time.sleep(FAILURE_PAUSE_SECONDS)
    return rc


def command_json(argv):
    """JSON printed by a command that ends within WATCH_TIMEOUT; None on any failure."""
    done = subprocess.run(bounded(argv, WATCH_TIMEOUT), capture_output=True, text=True)
    try:
        return None if done.returncode else json.loads(done.stdout)
    except ValueError:
        return None


def slot_units():
    """{slot: (ActiveState, seconds since it became active)}; one systemctl call for all slots."""
    shown = subprocess.run(
        bounded(["systemctl", "--user", "show", "ci-runner@*.service", "-p", "Id", "-p", "ActiveState",
                 "-p", "ActiveEnterTimestampMonotonic"], WATCH_TIMEOUT),
        capture_output=True, text=True,
    ).stdout
    units = {}
    for block in shown.split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if "Id" in fields:
            # systemd's monotonic stamps use the same clock as time.monotonic().
            age = time.monotonic() - int(fields["ActiveEnterTimestampMonotonic"]) / 1e6
            units[fields["Id"][len("ci-runner@"):-len(".service")]] = (fields["ActiveState"], age)
    return units


def container_states():
    """{container name: state} of every slot container and Docker sidecar, stopped ones too; None unless docker
    answered in time."""
    done = subprocess.run(
        bounded([*docker(), "ps", "--all", "--filter", "name=^/ci-(runner|dind)-", "--format", "{{.Names}} {{.State}}"],
                WATCH_TIMEOUT),
        capture_output=True, text=True,
    )
    if done.returncode:
        return None
    return dict(line.split(" ", 1) for line in done.stdout.splitlines())


def clear_container(name, wait=STOP_GRACE_SECONDS + 120):
    """Stop the container with a grace period, remove it, and wait until the daemon no longer
    lists it, so a new container of that name can start. False when it is still listed."""
    deadline, stopped = time.monotonic() + wait, False
    while True:
        listed = container_states()
        listed = None if listed is None else name in listed
        if listed is False:
            return True
        if time.monotonic() > deadline:
            return False
        if listed and not stopped:
            quiet([*docker(), "stop", "--time", str(STOP_GRACE_SECONDS), name])
            quiet([*docker(), "rm", "--force", name])
            stopped = True
        time.sleep(5)


def claim_container(name):
    """Free the slot's container name; raise when an old container still runs a job (it is left
    alone) or stays listed after its removal."""
    if busy(name.removeprefix("ci-runner-")):
        raise RuntimeError("the previous container still runs a job")
    if not clear_container(name):
        raise RuntimeError("the previous container is still listed after its removal")


def github_runners(repo):
    """The newest runner of each slot, by slot name, as GitHub lists it."""
    found = {}
    listed = command_json(["gh", "api", f"repos/{repo}/actions/runners?per_page=100"]) or {}
    for runner in sorted(listed.get("runners", []), key=lambda r: r["name"]):
        match = re.fullmatch(r"pool-(.+)-\d+", runner["name"])
        if match:
            found[match.group(1)] = runner
    return found


def missing_slots(units, containers, entries, seen, now):
    """{slot: when it was first seen without a container}: the active slots older than
    STALL_SECONDS that the daemon lists no container for."""
    return {
        instance: seen.get(instance, now)
        for instance, (state, age) in units.items()
        if state == "active" and age > STALL_SECONDS and instance.rpartition("-")[0] in entries
        and f"ci-runner-{instance}" not in containers
    }


def restart_due(missing, entries, now):
    """The slots (at most MAX_RESTARTS) that were missing for MISSING_SECONDS and whose runner
    GitHub shows offline and not busy."""
    runners, due = {}, []
    for instance, since in sorted(missing.items()):
        repo = entries[instance.rpartition("-")[0]]["repo"]
        if now - since < MISSING_SECONDS or len(due) == MAX_RESTARTS:
            continue
        if repo not in runners:
            runners[repo] = github_runners(repo)
        runner = runners[repo].get(instance)
        if runner and runner["status"] == "offline" and not runner["busy"]:
            due.append(instance)
    return due


def stuck_containers(containers, units):
    """Containers that the daemon cannot finish removing, whose slot unit is stopped."""
    return [
        name for name, state in sorted(containers.items())
        if state in ("removing", "dead")
        and units.get(name.split("-", 2)[2], ("inactive",))[0] in ("inactive", "failed")
    ]


def watch(dry_run=False):
    """Restart a slot that has no container, and whose runner GitHub shows offline and not busy.
    The slot must have run STALL_SECONDS, and the daemon must have listed no container for it
    in two successful reads MISSING_SECONDS apart (the first sighting is kept in WATCH_STATE).
    A failed or timed-out read acts on nothing and forgets every first sighting. Also removes
    containers stuck in `removing` or `dead` whose slot unit is stopped."""
    pool = {**DEFAULTS, **json.loads(CONFIG.read_text())}
    entries = {slug(entry["repo"]): entry for entry in pool["repos"]}
    containers, units, now = container_states(), slot_units(), time.time()
    if containers is None:
        containers = {}
        missing = {}
    else:
        seen = json.loads(WATCH_STATE.read_text()) if WATCH_STATE.exists() else {}
        missing = missing_slots(units, containers, entries, seen, now)
    verb = "would " if dry_run else ""
    for instance in restart_due(missing, entries, now):
        print(f"{verb}restart ci-runner@{instance}.service: runner offline on GitHub, no container for "
              f"{int(now - missing.pop(instance))} s", flush=True)
        if not dry_run:
            systemctl("restart", "--no-block", f"ci-runner@{instance}.service")
    for name in stuck_containers(containers, units):
        print(f"{verb}remove {name}: stuck, its slot is stopped", flush=True)
        if not dry_run:
            quiet([*docker(), "rm", "--force", name])
    if not dry_run:
        WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        WATCH_STATE.write_text(json.dumps(missing))
    return 0


def main(argv):
    if argv[:1] == ["apply"] and argv[1:] in ([], ["--check"]):
        return apply(check=argv[1:] == ["--check"])
    if argv[:1] == ["run"] and len(argv) == 2:
        return run(argv[1])
    if argv[:1] == ["watch"] and argv[1:] in ([], ["--dry-run"]):
        return watch(dry_run=bool(argv[1:]))
    if argv == ["image"]:
        return refresh_image()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
