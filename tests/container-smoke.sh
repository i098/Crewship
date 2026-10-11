#!/usr/bin/env bash
# Behavior smoke for the Crewship container worker image.
#
# Host mode (default when run outside the image):
#   tests/container-smoke.sh [--image REF] [--keep] [--only NAME,NAME]
#   Builds the Dockerfile `smoke` target and runs this same script inside the
#   resulting container with bounded memory/CPU/PID limits, then removes the
#   container and the image it created.
#
# Container mode (inside the image; CMD of the `smoke` target):
#   tests/container-smoke.sh --in-container [--only NAME,NAME]
#   Exercises what the image actually contains, through the programs a user
#   would run: managed tool versions compared with the releases the build
#   resolved, a Herdr
#   configuration that Herdr itself accepts and that matches the Crewship
#   document, the user unit's ExecStart resolved and executed, a real headless
#   `herdr server` brought up and shut down over its API socket, the repository
#   CLI (validate, invalid-input rejection, init overwrite refusal), a second
#   installer pass reporting changed=false, a `./ship.sh launch` that migrates
#   a pre-rename layout, and a second `./ship.sh launch` reporting changed=0.
#   No source-text assertions.
#
# Never used: --privileged, --pid=host, --network=host, the host Docker socket,
# or any bind of host home, credentials or browser profiles. No agent CLI is
# executed, so nothing can trigger an interactive login, and no browser or
# desktop profile is created.
#
# Environment knobs (host mode):
#   CF_SMOKE_IMAGE    use an existing image reference instead of building
#   CF_SMOKE_KEEP     non-empty: keep the built image after the run
#   CF_SMOKE_MEMORY   container memory cap        (default 4g)
#   CF_SMOKE_CPUS     container CPU cap           (default 2)
#   CF_SMOKE_PIDS     container PID cap           (default 4096)
#   CF_SMOKE_TIMEOUT  whole-container deadline, s (default 2700)
#   GITHUB_TOKEN      optional; authenticates the latest-herdr lookup (build
#                     secret and run env, never baked into the image)
# Environment knobs (container mode):
#   CF_SMOKE_ONLY           comma-separated check names
#   CF_SMOKE_APPLY_TIMEOUT  seconds for each ansible pass (default 1800)
#   CF_SMOKE_SERVER_WAIT    seconds to wait for the herdr server (default 30)

set -euo pipefail

SCRIPT_PATH=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")
REPO_ROOT=$(cd -- "$(dirname -- "${SCRIPT_PATH}")/.." && pwd)

MODE=auto
ONLY=${CF_SMOKE_ONLY:-}
KEEP=${CF_SMOKE_KEEP:-}
IMAGE_REF=${CF_SMOKE_IMAGE:-}

usage() {
    sed -n '2,40p' "${SCRIPT_PATH}" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --in-container) MODE=container ;;
        --host) MODE=host ;;
        --image) IMAGE_REF=${2:?--image needs a reference}; shift ;;
        --image=*) IMAGE_REF=${1#--image=} ;;
        --only) ONLY=${2:?--only needs check names}; shift ;;
        --only=*) ONLY=${1#--only=} ;;
        --keep) KEEP=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [ "${MODE}" = auto ]; then
    if [ -n "${CREWSHIP_IMAGE:-}" ] || [ -f /etc/crewship-image ]; then
        MODE=container
    else
        MODE=host
    fi
fi

# ---------------------------------------------------------------------------
# Host mode: build the smoke image, run this script inside it, clean up.
# ---------------------------------------------------------------------------
host_mode() {
    if ! command -v docker >/dev/null 2>&1; then
        printf 'docker is required for host mode; run with --in-container inside the image\n' >&2
        exit 2
    fi

    local rc
    # Globals: the EXIT trap below may run after this function has returned.
    SMOKE_BUILT=0
    SMOKE_CONTAINER="crewship-smoke-$$"
    if [ -n "${IMAGE_REF}" ]; then
        SMOKE_TAG=${IMAGE_REF}
    else
        SMOKE_TAG="crewship-smoke:$$"
    fi

    cleanup_host() {
        docker rm -f "${SMOKE_CONTAINER:-}" >/dev/null 2>&1 || true
        if [ "${SMOKE_BUILT:-0}" = 1 ] && [ -z "${KEEP}" ]; then
            docker image rm -f "${SMOKE_TAG:-}" >/dev/null 2>&1 || true
        fi
    }
    trap cleanup_host EXIT

    # GITHUB_TOKEN, when set, authenticates the latest-herdr lookup as a
    # BuildKit secret; unset, the secret is empty and the lookup is anonymous.
    if [ -z "${IMAGE_REF}" ]; then
        printf '==> docker build --target smoke --tag %s\n' "${SMOKE_TAG}"
        docker build --secret id=github_token,env=GITHUB_TOKEN \
            --target smoke --tag "${SMOKE_TAG}" "${REPO_ROOT}"
        SMOKE_BUILT=1
    fi

    printf '==> docker run %s (memory=%s cpus=%s pids=%s)\n' \
        "${SMOKE_TAG}" "${CF_SMOKE_MEMORY:-4g}" "${CF_SMOKE_CPUS:-2}" "${CF_SMOKE_PIDS:-4096}"

    # Default bridge networking is kept: the second ansible pass may resolve
    # package or artifact sources. No port is published and no volume is bound.
    # No --privileged, no --pid=host, no --network=host, no socket mount.
    rc=0
    timeout "${CF_SMOKE_TIMEOUT:-2700}" \
        docker run --rm --name "${SMOKE_CONTAINER}" --init \
            --memory "${CF_SMOKE_MEMORY:-4g}" \
            --memory-swap "${CF_SMOKE_MEMORY:-4g}" \
            --cpus "${CF_SMOKE_CPUS:-2}" \
            --pids-limit "${CF_SMOKE_PIDS:-4096}" \
            --cap-drop NET_RAW \
            --tmpfs /tmp:rw,nosuid,nodev,size=1g,mode=1777 \
            --env CF_SMOKE_ONLY="${ONLY}" \
            --env CF_SMOKE_APPLY_TIMEOUT="${CF_SMOKE_APPLY_TIMEOUT:-1800}" \
            --env CF_SMOKE_SERVER_WAIT="${CF_SMOKE_SERVER_WAIT:-30}" \
            --env GITHUB_TOKEN \
            "${SMOKE_TAG}" /opt/crewship/tests/container-smoke.sh --in-container || rc=$?

    if [ "${rc}" -eq 124 ]; then
        printf 'smoke container exceeded CF_SMOKE_TIMEOUT=%s seconds\n' "${CF_SMOKE_TIMEOUT:-2700}" >&2
    fi
    return "${rc}"
}

# ---------------------------------------------------------------------------
# Container mode: harness
# ---------------------------------------------------------------------------
CREWSHIP_USER_EXPECTED=${CREWSHIP_USER:-coder}
CREWSHIP_HOME_EXPECTED=${CREWSHIP_HOME:-/home/coder}
CREWSHIP_WORKSPACE_EXPECTED=${CREWSHIP_WORKSPACE:-${CREWSHIP_HOME_EXPECTED}/Dev}
CF_ROOT=${CREWSHIP_ROOT:-/opt/crewship}
CF_CONFIG=${CREWSHIP_CONFIG:-${CF_ROOT}/containers/crewship.container.yml}

CHECKS_TOTAL=0
CHECKS_RUN=0
CHECKS_FAILED=0
FAILED_NAMES=""

fail() {
    printf 'assertion failed: %s\n' "$*" >&2
    exit 1
}

should_run() {
    [ -z "${ONLY}" ] && return 0
    case ",${ONLY}," in
        *",$1,"*) return 0 ;;
        *) return 1 ;;
    esac
}

run_check() {
    local name=$1
    shift
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    if ! should_run "${name}"; then
        printf 'skip  %s\n' "${name}"
        return 0
    fi
    CHECKS_RUN=$((CHECKS_RUN + 1))
    local log start elapsed
    log="${SMOKE_TMP}/${name}.log"
    start=${SECONDS}
    if ( "$@" ) >"${log}" 2>&1; then
        elapsed=$((SECONDS - start))
        printf 'ok    %-32s %3ss\n' "${name}" "${elapsed}"
        sed 's/^/        /' "${log}"
    else
        elapsed=$((SECONDS - start))
        CHECKS_FAILED=$((CHECKS_FAILED + 1))
        FAILED_NAMES="${FAILED_NAMES} ${name}"
        printf 'FAIL  %-32s %3ss\n' "${name}" "${elapsed}"
        tail -n 40 "${log}" | sed 's/^/      | /'
    fi
}

platform_tag() {
    case "$(uname -m)" in
        x86_64|amd64) printf 'linux-x86_64\n' ;;
        aarch64|arm64) printf 'linux-aarch64\n' ;;
        *) fail "unsupported architecture $(uname -m)" ;;
    esac
}

# Python that can read YAML: the image builds the repository virtualenv from the
# locked dependencies during ./onboard.sh.
cf_python() {
    if [ -x "${CF_ROOT}/.venv/bin/python" ]; then
        "${CF_ROOT}/.venv/bin/python" "$@"
    else
        ( cd "${CF_ROOT}" && uv run --project "${CF_ROOT}" python "$@" )
    fi
}

# Every tool tracks its latest release. The installer records the releases it installed in RESOLVED_STAMP; checks compare
# against that record, so an upstream release published after the build cannot
# turn them red.
RESOLVED_STAMP="${HOME}/.local/share/crewship/resolved.json"
resolved_version() {
    jq -er "$1" "${RESOLVED_STAMP}"
}

# The contract computes the Herdr service binary from the installed release,
# never from PATH.
herdr_installed_bin() {
    printf '%s/.local/share/crewship/tools/herdr/%s/%s/herdr\n' \
        "${HOME}" "$(resolved_version .herdr.version)" "$(platform_tag)"
}

# A second apply resolves upstream again and upgrades an image that upstream
# has since overtaken; that is an upgrade, not a repeat change.
image_is_current() {
    local latest versions='map_values(.version? // .)'
    latest=$(python3 "${CF_ROOT}/scripts/provisions.py" \
        --home "${HOME}" --tools herdr,node,bun,uv,btop,sentrux,fallow,pyrefly,nvim --npm --development --resolve) \
        || fail "could not resolve the latest releases"
    [ "$(jq -cS "${versions}" <<<"${latest}")" = "$(jq -cS "${versions}" "${RESOLVED_STAMP}")" ] \
        && return 0
    printf 'image has %s but upstream now has %s; idempotence not measured\n' \
        "$(jq -cS "${versions}" "${RESOLVED_STAMP}")" "$(jq -cS "${versions}" <<<"${latest}")"
    return 1
}

# ---------------------------------------------------------------------------
# Container mode: checks
# ---------------------------------------------------------------------------

check_identity() {
    [ "$(id -u)" -ne 0 ] || fail "image runs as root; the worker must be non-root"
    [ "$(id -un)" = "${CREWSHIP_USER_EXPECTED}" ] || fail "user is $(id -un), expected ${CREWSHIP_USER_EXPECTED}"
    [ "${HOME}" = "${CREWSHIP_HOME_EXPECTED}" ] || fail "HOME is ${HOME}, expected ${CREWSHIP_HOME_EXPECTED}"
    [ -w "${HOME}" ] || fail "home is not writable"
    printf 'uid=%s user=%s home=%s shell=%s\n' "$(id -u)" "$(id -un)" "${HOME}" "${SHELL:-unset}"
}

check_no_systemd() {
    local pid1
    pid1=$(cat /proc/1/comm 2>/dev/null || printf 'unknown\n')
    case "${pid1}" in
        *systemd*) fail "PID 1 is ${pid1}; this image must not claim a running init system" ;;
    esac
    [ ! -d /run/systemd/system ] || fail "/run/systemd/system exists; systemd appears to be running"
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-system-running >/dev/null 2>&1; then
            fail "systemctl reports a running system manager inside the container"
        fi
    fi
    [ ! -e "/var/lib/systemd/linger/${CREWSHIP_USER_EXPECTED}" ] || fail "linger marker present; enable_linger must be suppressed"
    printf 'pid1=%s no systemd, no linger marker (start_services=false honored)\n' "${pid1}"
}

check_no_host_surface() {
    local p
    for p in /var/run/docker.sock /run/docker.sock /host /hostfs /run/host; do
        [ ! -e "${p}" ] || fail "host surface leaked into the container: ${p}"
    done
    if [ -e "${HOME}/.vnc-chrome-profile" ] || [ -e "${HOME}/.vnc" ]; then
        fail "desktop/browser profile state present in the image"
    fi
    # A shared host PID namespace would expose host daemons; an ordinary
    # container sees only its own small process tree.
    local host_procs
    host_procs=$(ps -eo comm= 2>/dev/null | grep -E '^(systemd|dockerd|containerd|tailscaled|sshd|Xvnc|websockify)$' || true)
    [ -z "${host_procs}" ] || fail "host processes visible in the container: $(printf '%s' "${host_procs}" | tr '\n' ' ')"
    printf 'no docker socket, host mount, desktop or browser profile state\n'
}

check_profiles_disabled() {
    local b
    for b in docker dockerd tailscale tailscaled Xvnc vncserver x0vncserver websockify xfce4-session startxfce4; do
        if command -v "${b}" >/dev/null 2>&1; then
            fail "${b} is installed; the docker/tailscale/desktop profiles must be false in a container"
        fi
    done
    [ ! -e /usr/sbin/tailscaled ] || fail "tailscaled binary present"
    printf 'docker, tailscale and desktop profiles produced no binaries\n'
}

check_source_checkout() {
    [ -d "${CF_ROOT}" ] || fail "missing source checkout at ${CF_ROOT}"
    [ -f "${CF_ROOT}/pyproject.toml" ] || fail "missing ${CF_ROOT}/pyproject.toml"
    [ -x "${CF_ROOT}/ship.sh" ] || fail "missing executable ${CF_ROOT}/ship.sh"
    [ -x "${CF_ROOT}/onboard.sh" ] || fail "missing executable ${CF_ROOT}/onboard.sh"
    [ -f "${CF_CONFIG}" ] || fail "missing container configuration ${CF_CONFIG}"
    local owner
    owner=$(stat -c %U "${CF_ROOT}")
    [ "${owner}" = "${CREWSHIP_USER_EXPECTED}" ] || fail "${CF_ROOT} owned by ${owner}, expected ${CREWSHIP_USER_EXPECTED}"
    printf 'checkout %s owned by %s, config %s\n' "${CF_ROOT}" "${owner}" "${CF_CONFIG}"
}

check_workspace() {
    local probe owner
    [ -d "${CREWSHIP_WORKSPACE_EXPECTED}" ] || fail "missing workspace ${CREWSHIP_WORKSPACE_EXPECTED}"
    owner=$(stat -c %U "${CREWSHIP_WORKSPACE_EXPECTED}")
    [ "${owner}" = "${CREWSHIP_USER_EXPECTED}" ] || fail "workspace owned by ${owner}"
    probe="${CREWSHIP_WORKSPACE_EXPECTED}/.container-smoke-probe.$$"
    : >"${probe}" || fail "workspace is not writable"
    rm -f "${probe}"
    printf 'workspace %s writable and owned by %s\n' "${CREWSHIP_WORKSPACE_EXPECTED}" "${owner}"
}

check_core_tools() {
    local tool bin expected version
    for tool in node bun uv; do
        bin="${HOME}/.local/bin/${tool}"
        [ -x "${bin}" ] || fail "missing managed launcher ${bin}"
        [ "$(command -v "${tool}")" = "${bin}" ] || fail "PATH resolves ${tool} to $(command -v "${tool}"), expected ${bin}"
        version=$("${bin}" --version 2>&1) || fail "${tool} --version exited nonzero: ${version}"
        version=${version%%$'\n'*}
        [ -n "${version}" ] || fail "${tool} --version produced no output"
        # An existing command is not enough: it must be the release the build resolved.
        expected=$(resolved_version ".${tool}.version") || fail "${RESOLVED_STAMP} records no ${tool}"
        case "${version}" in
            *"${expected}"*) ;;
            *) fail "${tool} reports '${version}' but expected ${expected}" ;;
        esac
        printf '%-6s %-32s (expected %s)\n' "${tool}" "${version}" "${expected}"
    done
}

# The installed herdr, gh, no-mistakes, treehouse, gws, nvim, omp, AXI tools, acpx and
# chrome-devtools-mcp are exactly
# the releases the build resolved and recorded in RESOLVED_STAMP.
check_resolved_releases() {
    local tool version banner package prefix
    [ -f "${RESOLVED_STAMP}" ] || fail "installer wrote no ${RESOLVED_STAMP}"
    for tool in herdr gh no-mistakes treehouse gws nvim; do
        version=$(resolved_version ".\"${tool}\".version")
        banner=$("${HOME}/.local/bin/${tool}" --version 2>&1) || fail "${tool} --version exited nonzero: ${banner}"
        case "${banner%%$'\n'*}" in
            *"${version}"*) ;;
            *) fail "${tool} reports '${banner%%$'\n'*}' but the build resolved ${version}" ;;
        esac
        printf '%s %s\n' "${tool}" "${version}"
    done
    for tool in omp:@oh-my-pi/pi-coding-agent chrome-devtools-axi gh-axi lavish-axi quota-axi tasks-axi acpx \
        chrome-devtools-mcp; do
        package=${tool#*:}; tool=${tool%%:*}
        version=$(resolved_version ".\"${tool}\"")
        prefix="${HOME}/.local/share/crewship/${tool}/${version}"
        case "$(readlink -f "${HOME}/.local/bin/${tool}")" in
            "${prefix}"/*) ;;
            *) fail "${tool} resolves to $(readlink -f "${HOME}/.local/bin/${tool}"), expected the resolved release under ${prefix}" ;;
        esac
        [ "$(jq -r .version "${prefix}/node_modules/${package}/package.json")" = "${version}" ] \
            || fail "${tool} under ${prefix} is not version ${version}"
        printf '%s %s\n' "${tool}" "${version}"
    done
    printf 'installed releases match %s\n' "${RESOLVED_STAMP}"
}

check_herdr_install_layout() {
    local link target platform expected_prefix herdr_banner
    link="${HOME}/.local/bin/herdr"
    target=$(readlink -f "${link}")
    platform=$(platform_tag)
    expected_prefix="${HOME}/.local/share/crewship/tools/herdr/"
    case "${target}" in
        "${expected_prefix}"*/"${platform}"/herdr) ;;
        *) fail "herdr resolves to ${target}, expected ${expected_prefix}<version>/${platform}/herdr" ;;
    esac
    [ -x "${target}" ] || fail "resolved herdr executable is not executable"
    herdr_banner=$("${target}" --version 2>&1) || fail "versioned herdr executable failed to run"
    case "${herdr_banner%%$'\n'*}" in
        *herdr*) ;;
        *) fail "versioned herdr executable did not identify itself" ;;
    esac
    printf 'herdr symlink -> %s\n' "${target}"
}

check_development_toolchain() {
    local tool path version
    for tool in rustc cargo; do
        path=$(command -v "${tool}" 2>/dev/null || true)
        [ -n "${path}" ] || fail "development profile selected but ${tool} is not on PATH"
        case "${path}" in
            "${HOME}"/*) ;;
            *) fail "${tool} resolves to ${path}, expected a user-scoped rustup install under ${HOME}" ;;
        esac
        version=$("${path}" --version 2>&1) || fail "${tool} --version exited nonzero: ${version}"
        version=${version%%$'\n'*}
        [ -n "${version}" ] || fail "${tool} --version produced no output"
        printf '%-6s %s (%s)\n' "${tool}" "${version}" "${path}"
    done
}

check_no_baked_credentials() {
    local p
    for p in \
        "${HOME}/.ssh" "${HOME}/.netrc" "${HOME}/.aws" "${HOME}/.config/gh" \
        "${HOME}/.config/omp/auth.json" "${HOME}/.claude/.credentials.json" \
        "${HOME}/.codex/auth.json" \
        "${CF_ROOT}/.env" "${CF_ROOT}/.local/secrets"; do
        [ ! -e "${p}" ] || fail "credential-bearing path baked into the image: ${p}"
    done
    if [ -f "${HOME}/.npmrc" ] && grep -q '_authToken' "${HOME}/.npmrc"; then
        fail "npm auth token baked into the image"
    fi
    printf 'no credential stores, tokens or .env files in the image\n'
}

check_herdr_config() {
    local cfg report
    cfg="${HOME}/.config/herdr/config.toml"
    [ -f "${cfg}" ] || fail "missing rendered Herdr configuration ${cfg}"

    # Herdr's own validator decides whether the rendered file is usable.
    report=$(herdr config check 2>&1) || {
        printf '%s\n' "${report}"
        fail "herdr config check rejected ${cfg}"
    }

    # ...and the values it accepted must be the ones the Crewship document asks
    # for, so a silently ignored key cannot pass as "configured".
    cf_python - "${cfg}" "${CF_ROOT}/config/default.yml" "${CF_CONFIG}" <<'PY'
import sys
import tomllib

import yaml

config_path, defaults_path, document_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(config_path, "rb") as fh:
    rendered = tomllib.load(fh)
with open(defaults_path, encoding="utf-8") as fh:
    wanted = yaml.safe_load(fh)["crewship"]["herdr"]
with open(document_path, encoding="utf-8") as fh:
    wanted.update(yaml.safe_load(fh)["crewship"]["herdr"])

actual = {
    "theme": rendered.get("theme", {}).get("name"),
    "toast_delivery": rendered.get("ui", {}).get("toast", {}).get("delivery"),
    "agent_panel_sort": rendered.get("ui", {}).get("agent_panel_sort"),
    "headless_cols": rendered.get("server", {}).get("headless_cols"),
    "headless_rows": rendered.get("server", {}).get("headless_rows"),
    "sidebar_width": rendered.get("ui", {}).get("sidebar_width"),
    "sidebar_max_width": rendered.get("ui", {}).get("sidebar_max_width"),
    "sidebar_bg": rendered.get("theme", {}).get("custom", {}).get("sidebar_bg"),
    "sidebar_agent_rows": rendered.get("ui", {}).get("sidebar", {}).get("agents", {}).get("rows"),
    "sidebar_space_rows": rendered.get("ui", {}).get("sidebar", {}).get("spaces", {}).get("rows"),
}
# The document carries the layouts as TOML text; compare them parsed.
for key in ("sidebar_agent_rows", "sidebar_space_rows"):
    wanted[key] = tomllib.loads("rows = " + wanted[key])["rows"]
mismatched = {key: (actual[key], value) for key, value in wanted.items() if key in actual and actual[key] != value}
if mismatched:
    raise SystemExit(f"rendered Herdr config disagrees with the Crewship document (actual, wanted): {mismatched}")
if rendered.get("experimental", {}).get("pane_history"):
    raise SystemExit("experimental.pane_history is enabled; pane output can carry secrets")
if rendered.get("onboarding", False):
    raise SystemExit("onboarding is enabled; a provisioned image must not prompt on first run")

for key in ("sidebar_agent_rows", "sidebar_space_rows"):
    actual[key] = f"{len(actual[key] or [])} rows"
print("rendered config matches the document: " + ", ".join(f"{k}={v}" for k, v in sorted(actual.items())))
PY
    printf 'herdr config check: %s\n' "${report%%$'\n'*}"
}

# start_services=false still has to produce a unit a real host can boot, so the
# unit's ExecStart is resolved and executed here instead of being read as text.
check_herdr_unit() {
    local unit wants expected exec_start binary banner locked
    unit="${HOME}/.config/systemd/user/herdr.service"
    wants="${HOME}/.config/systemd/user/default.target.wants/herdr.service"
    [ -f "${unit}" ] || fail "missing rendered user unit ${unit}"

    exec_start=$(sed -n 's/^ExecStart=//p' "${unit}" | head -n 1)
    [ -n "${exec_start}" ] || fail "${unit} declares no ExecStart"
    expected="$(herdr_installed_bin) server"
    [ "${exec_start}" = "${expected}" ] || fail "ExecStart is '${exec_start}', expected '${expected}'"

    binary=${exec_start%% *}
    [ -x "${binary}" ] || fail "ExecStart binary ${binary} is missing or not executable"
    locked=$(resolved_version .herdr.version)
    banner=$("${binary}" --version 2>&1) || fail "ExecStart binary ${binary} failed to run"
    banner=${banner%%$'\n'*}
    case "${banner}" in
        *"${locked}"*) ;;
        *) fail "ExecStart binary reports '${banner}', the installed release is ${locked}" ;;
    esac

    [ -L "${wants}" ] || fail "unit is not statically enabled: ${wants} is missing"
    [ "$(readlink -f "${wants}")" = "$(readlink -f "${unit}")" ] || fail "${wants} does not resolve to ${unit}"

    # Written and enabled, never started: start_services=false.
    if pgrep -x herdr >/dev/null 2>&1; then
        fail "a herdr process is already running in the image; provisioning must not start services"
    fi
    printf 'unit ExecStart=%s runs %s, statically enabled, not started\n' "${exec_start}" "${banner}"
}

check_herdr_server_headless() {
    local binary log pid socket status waited started_after limit stopped leftover
    binary=$(herdr_installed_bin)
    log="${SMOKE_TMP}/herdr-server.log"
    limit=${CF_SMOKE_SERVER_WAIT:-30}
    pid=""

    stop_server() {
        if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
            kill -TERM "${pid}" 2>/dev/null || true
            for _ in $(seq 1 10); do
                kill -0 "${pid}" 2>/dev/null || break
                sleep 1
            done
            kill -KILL "${pid}" 2>/dev/null || true
        fi
    }
    trap stop_server EXIT

    # Exactly what the user unit would run: the locked build, headless, no
    # DISPLAY, no terminal. Nothing here opens a browser or an interactive login.
    ( unset DISPLAY; exec "${binary}" server ) >"${log}" 2>&1 &
    pid=$!

    waited=0
    status=""
    while [ "${waited}" -lt "${limit}" ]; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            tail -n 20 "${log}" || true
            fail "herdr server exited after ${waited}s instead of serving"
        fi
        status=$(herdr status server 2>&1 || true)
        case "${status}" in
            *"status: running"*) break ;;
        esac
        sleep 1
        waited=$((waited + 1))
    done

    case "${status}" in
        *"status: running"*) ;;
        *)
            printf '%s\n' "${status}"
            tail -n 20 "${log}" || true
            fail "herdr status server never reported a running server within ${limit}s"
            ;;
    esac
    started_after=${waited}

    socket=$(printf '%s\n' "${status}" | sed -n 's/^[[:space:]]*socket:[[:space:]]*//p' | head -n 1)
    [ -n "${socket}" ] || fail "herdr status server reported no socket path"
    [ -S "${socket}" ] || fail "reported API socket ${socket} is not a socket"
    case "${socket}" in
        "${HOME}"/*) ;;
        *) fail "server socket ${socket} lives outside ${HOME}" ;;
    esac

    # Documented shutdown path: over the API socket, not a signal.
    herdr server stop >"${SMOKE_TMP}/herdr-stop.log" 2>&1 || {
        tail -n 20 "${SMOKE_TMP}/herdr-stop.log" || true
        fail "herdr server stop failed while a server was running"
    }

    stopped=0
    for waited in $(seq 1 15); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            stopped=1
            break
        fi
        sleep 1
    done
    if [ "${stopped}" -ne 1 ]; then
        stop_server
        trap - EXIT
        fail "the server process survived 'herdr server stop'"
    fi
    wait "${pid}" 2>/dev/null || true
    trap - EXIT

    status=$(herdr status server 2>&1 || true)
    case "${status}" in
        *"status: running"*) fail "herdr still reports a running server after stop" ;;
    esac

    for leftover in "${HOME}/.vnc-chrome-profile" "${HOME}/.vnc" "${HOME}/.config/chromium" "${HOME}/.config/google-chrome"; do
        [ ! -e "${leftover}" ] || fail "server run created desktop/browser state: ${leftover}"
    done
    printf 'headless server answered on %s after %ss and stopped over the API socket; no GUI state created\n' \
        "${socket}" "${started_after}"
}

check_ship_inspect() {
    ( cd "${CF_ROOT}" && ./ship.sh inspect --config "${CF_CONFIG}" ) || fail "./ship.sh inspect rejected the container configuration"
    printf './ship.sh inspect --config %s accepted\n' "${CF_CONFIG}"
}

check_ship_inspect_rejects_invalid() {
    local bad
    bad="${SMOKE_TMP}/invalid-config.yml"
    cat >"${bad}" <<'YAML'
schema_version: 99
crewship:
  user: 42
  home: /home/coder
  start_services: definitely
  profiles:
    agents: "yes"
YAML
    if ( cd "${CF_ROOT}" && ./ship.sh inspect --config "${bad}" ) >/dev/null 2>&1; then
        fail "./ship.sh inspect accepted a structurally invalid configuration"
    fi
    rm -f "${bad}"
    printf './ship.sh inspect rejected an invalid document as expected\n'
}

check_ship_dock_refuses_overwrite() {
    local host_yml backup
    host_yml="${CF_ROOT}/.local/host.yml"
    backup="${SMOKE_TMP}/host.yml.backup"

    restore_host_yml() {
        rm -f "${host_yml}"
        if [ -f "${backup}" ]; then
            mkdir -p "$(dirname "${host_yml}")"
            mv "${backup}" "${host_yml}"
        fi
    }
    trap restore_host_yml EXIT

    if [ -f "${host_yml}" ]; then
        cp "${host_yml}" "${backup}"
        rm -f "${host_yml}"
    fi

    ( cd "${CF_ROOT}" && ./ship.sh dock --container --user "${CREWSHIP_USER_EXPECTED}" --home "${CREWSHIP_HOME_EXPECTED}" ) \
        || fail "./ship.sh dock --container failed"
    [ -f "${host_yml}" ] || fail "./ship.sh dock did not write ${host_yml}"

    if ( cd "${CF_ROOT}" && ./ship.sh dock --container --user "${CREWSHIP_USER_EXPECTED}" --home "${CREWSHIP_HOME_EXPECTED}" ) >/dev/null 2>&1; then
        fail "./ship.sh dock overwrote an existing ${host_yml} without an explicit flag"
    fi

    restore_host_yml
    trap - EXIT
    printf './ship.sh dock wrote .local/host.yml once and refused to overwrite it\n'
}

check_installer_idempotent() {
    local out
    out=$(python3 "${CF_ROOT}/scripts/provisions.py" \
            --home "${HOME}" \
            --tools herdr,node,bun,uv,btop,sentrux,fallow,pyrefly,nvim \
            --resolved "$(cat "${RESOLVED_STAMP}")" \
            --npm --development 2>&1) || {
        printf '%s\n' "${out}" | tail -n 20
        fail "scripts/provisions.py re-run failed"
    }
    printf '%s\n' "${out}" >"${SMOKE_TMP}/installer.out"
    python3 - "${SMOKE_TMP}/installer.out" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    lines = [line for line in fh.read().splitlines() if line.strip()]

if not lines:
    raise SystemExit("installer produced no output")

try:
    result = json.loads(lines[-1])
except json.JSONDecodeError as exc:
    raise SystemExit("final installer line is not JSON: {!r} ({})".format(lines[-1], exc))

if result.get("changed") is not False:
    raise SystemExit("installer re-run reported changed={!r}: {}".format(result.get("changed"), result))

print("installer re-run changed=false, installed entries:", len(result.get("installed", [])))
PY
}

check_ansible_second_pass_idempotent() {
    local out rc
    rc=0
    image_is_current || return 0
    out=$( cd "${CF_ROOT}" && timeout "${CF_SMOKE_APPLY_TIMEOUT:-1800}" ./ship.sh launch --config "${CF_CONFIG}" 2>&1 ) || rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf '%s\n' "${out}" | tail -n 40
        fail "second ./ship.sh launch exited ${rc}"
    fi
    printf '%s\n' "${out}" | awk '
        /PLAY RECAP/ { recap = 1; next }
        recap && /changed=/ {
            hosts++
            if ($0 !~ /changed=0([^0-9]|$)/) bad++
            if ($0 !~ /failed=0([^0-9]|$)/) bad++
            if ($0 !~ /unreachable=0([^0-9]|$)/) bad++
            print "recap: " $0
        }
        END {
            if (hosts == 0) { print "no PLAY RECAP host lines found" > "/dev/stderr"; exit 1 }
            if (bad > 0) { print "second apply was not idempotent" > "/dev/stderr"; exit 1 }
            print "second apply idempotent across " hosts " host line(s)"
        }
    ' || fail "second ./ship.sh launch did not report changed=0/failed=0/unreachable=0"
}

# A host installed before the Crewship rename. The old name comes from the
# migration table in ansible/tasks/rename.yml, so no path is listed twice.
# ansible-second-pass runs next and proves the second apply changes nothing.
check_rename_migration() {
    local old units share state out rc link path renamed unit bridge bridge_pid other_pid
    old=$(cf_python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))[0]["vars"]["crewship_renamed_word"])' \
        "${CF_ROOT}/ansible/tasks/rename.yml") || fail "cannot read the old name from ansible/tasks/rename.yml"
    units="${HOME}/.config/systemd/user"
    share="${HOME}/.local/share"
    state="${HOME}/.local/state"
    launch() { ( cd "${CF_ROOT}" && timeout "${CF_SMOKE_APPLY_TIMEOUT:-1800}" ./ship.sh launch --config "${CF_CONFIG}" 2>&1 ); }

    # Every renamed path that exists goes back to its old name, then the old
    # layout gets data, the desktop units and a proxy drop-in that hosts have.
    renamed=("${share}/crewship" "${state}/crewship" "${HOME}/.cache/crewship" /var/lib/crewship
        "${units}/no-mistakes-daemon-.service.d/crewship.conf" "${units}/headroom.service.d/crewship-thinking-guard.conf"
        "${HOME}/.omp/agent/extensions/crewship-herdr-sidebar.ts" "${HOME}/.omp/agent/extensions/crewship-quality-gate.ts")
    for path in "${renamed[@]}"; do
        [ ! -e "${path}" ] || sudo mv -T "${path}" "${path//crewship/${old}}"
    done
    for link in "${HOME}"/.local/bin/*; do
        case "$(readlink "${link}")" in
            "${share}/crewship/"*) ln -sfn "$(readlink "${link}" | sed "s#^${share}/crewship/#${share}/${old}/#")" "${link}" ;;
        esac
    done
    mkdir -p "${state}/${old}/secrets" "${HOME}/.cache/${old}" "${units}/headroom.service.d"
    printf 'kept\n' >"${share}/${old}/rename-probe"
    printf 'secret\n' >"${state}/${old}/secrets/postgres_password"
    printf 'cached\n' >"${HOME}/.cache/${old}/rename-probe"
    sudo mkdir -p "/var/lib/${old}"
    printf 'prerequisites\n' | sudo tee "/var/lib/${old}/cloud-init-prerequisites" >/dev/null
    printf '[Service]\nExecStartPre="%s/%s/proxy-fixes/headroom-check.py"\n' "${share}" "${old}" \
        >"${units}/headroom.service.d/${old}-thinking-guard.conf"
    grep -rl "${share}/crewship/" "${units}" | xargs -r sed -i "s#${share}/crewship/#${share}/${old}/#g"
    for unit in vnc novnc; do
        printf '[Service]\nExecStart=/bin/true\n' >"${units}/${old}-${unit}.service"
        ln -sfn "${units}/${old}-${unit}.service" "${units}/default.target.wants/${old}-${unit}.service"
        renamed+=("${units}/crewship-${unit}.service" "${units}/default.target.wants/crewship-${unit}.service")
    done
    sed -i "s/^# \(BEGIN\|END\) crewship managed environment\$/# \1 ${old} managed environment/; s#${share}/crewship/#${share}/${old}/#g" \
        "${HOME}/.profile"

    # A bridge that runs from the old directory, and a process that only names its path.
    bridge="${share}/${old}/chrome-devtools-axi/0.0.0-smoke/node_modules/chrome-devtools-axi/dist/bin/chrome-devtools-axi-bridge.js"
    mkdir -p "${bridge%/*}"
    printf 'setInterval(() => {}, 1000);\n' >"${bridge}"
    node "${bridge}" </dev/null >/dev/null 2>&1 &
    bridge_pid=$!
    node -e 'setInterval(() => {}, 1000);' "${bridge}" </dev/null >/dev/null 2>&1 &
    other_pid=$!
    running() { [ -e "/proc/$1" ] && ! grep -q '^State:[[:space:]]*Z' "/proc/$1/status"; }

    # An old path beside its new name stops the apply and moves nothing.
    mkdir "${HOME}/.cache/crewship"
    rc=0
    out=$(launch) || rc=$?
    [ "${rc}" -ne 0 ] || fail "the apply ran although an old path and its new name both exist"
    grep -q 'Both the old and the new path exist' <<<"${out}" || { printf '%s\n' "${out}" | tail -n 40; fail "the apply failed for another reason"; }
    [ -f "${share}/${old}/rename-probe" ] && [ ! -e "${share}/crewship" ] || fail "the refused apply moved data"
    [ -f "${units}/${old}-vnc.service" ] && [ -L "${units}/default.target.wants/${old}-vnc.service" ] || fail "the refused apply deleted the old units"
    running "${bridge_pid}" || fail "the refused apply stopped a bridge"
    rmdir "${HOME}/.cache/crewship"

    rc=0
    out=$(launch) || rc=$?
    [ "${rc}" -eq 0 ] || { printf '%s\n' "${out}" | tail -n 40; fail "./ship.sh launch on the old layout exited ${rc}"; }
    ! running "${bridge_pid}" || fail "the bridge that runs from the old directory still runs"
    grep -qF "${bridge_pid} ${bridge} stopped" <<<"${out}" || fail "the apply did not log the stopped bridge"
    running "${other_pid}" || fail "the apply stopped a process that only names the old bridge path"
    kill "${other_pid}"
    wait "${bridge_pid}" "${other_pid}" || true
    rm -rf "${share}/crewship/chrome-devtools-axi/0.0.0-smoke"

    [ "$(cat "${share}/crewship/rename-probe")" = kept ] || fail "the share directory data did not move"
    [ "$(cat "${state}/crewship/secrets/postgres_password")" = secret ] || fail "the state directory data did not move"
    [ "$(cat "${HOME}/.cache/crewship/rename-probe")" = cached ] || fail "the cache directory data did not move"
    [ "$(cat /var/lib/crewship/cloud-init-prerequisites)" = prerequisites ] || fail "the system directory data did not move"
    # The desktop profile is off in a container, so only its old units must go.
    for path in "${renamed[@]}"; do
        case "${path}" in
            *-vnc.service|*-novnc.service) ;;
            *) [ -e "${path}" ] || fail "${path} is missing" ;;
        esac
        [ ! -e "${path//crewship/${old}}" ] && [ ! -L "${path//crewship/${old}}" ] || fail "${path//crewship/${old}} is still present"
    done
    ! grep -rq "${old}" "${units}" "${HOME}/.profile" || fail "a user unit or ~/.profile still names ${old}: $(grep -rl "${old}" "${units}" "${HOME}/.profile" | tr '\n' ' ')"
    [ "$(grep -c '^# BEGIN crewship managed environment$' "${HOME}/.profile")" = 1 ] || fail "~/.profile does not have exactly one managed block"
    [ -z "$(find "${HOME}/.local/bin" -xtype l)" ] || fail "dangling command links: $(find "${HOME}/.local/bin" -xtype l | tr '\n' ' ')"
    printf 'old layout migrated in one apply: data moved, old units and paths gone, links and units on the new paths\n'
}

# The managed ~/.profile block is what a real interactive session gets, so it is
# probed through an actual login shell rather than read as text.
check_login_shell_environment() {
    local resolved mcp
    resolved=$(bash -lc 'command -v herdr') || fail "a login shell cannot resolve herdr"
    [ "${resolved}" = "${HOME}/.local/bin/herdr" ] || fail "login shell resolves herdr to ${resolved}, expected ${HOME}/.local/bin/herdr"
    mcp=$(bash -lc 'printf "%s" "${CHROME_DEVTOOLS_AXI_MCP_PATH:-}"')
    [ -n "${mcp}" ] || fail "login shell does not export CHROME_DEVTOOLS_AXI_MCP_PATH although the agents profile is on"
    [ -f "${mcp}" ] || fail "CHROME_DEVTOOLS_AXI_MCP_PATH=${mcp} does not exist; AXI would fall back to a floating npx package"
    printf 'login shell resolves %s and pins the MCP entrypoint at %s\n' "${resolved}" "${mcp}"
}

# What the no-mistakes gate and the PR review need on a fresh host: omp as the
# gate agent (docs/omp.md#no-mistakes-pipeline-agent), acpx mapping omp to
# `omp acp`, no omp
# registry override, ponytail-review's exit codes against a stub omp, and the
# fleet's minimum AXI versions. Versions come from RESOLVED_STAMP, which
# resolved-releases matched against the installed package.json.
check_agent_gate() {
    local name floor version stub row want omp_rc omp_out rc
    cf_python -c 'import sys, yaml; c = yaml.safe_load(open(sys.argv[1])); assert "acp_registry_overrides" not in c and (c["agent"] == ["acp:omp"] or (c["agent"] == "pi" and c["agent_path_override"]["pi"] == sys.argv[2]))' \
        "${HOME}/.no-mistakes/config.yaml" "${HOME}/.no-mistakes/omp-as-pi/omp-as-pi" || fail "~/.no-mistakes/config.yaml makes neither omp-as-pi nor acp:omp the gate agent"
    "${HOME}/.no-mistakes/omp-as-pi/omp-as-pi" --omp-as-pi-check || fail "the omp-as-pi preflight failed"
    [ -f "${HOME}/.omp/agent/extensions/fm-no-pattern-kill.ts" ] || fail "the pattern-kill guard omp extension is not installed"
    [ -f "${HOME}/.omp/agent/extensions/crewship-quality-gate.ts" ] || fail "the quality gate omp extension is not installed"
    jq -e '.agents.omp.command == "omp acp"' "${HOME}/.acpx/config.json" >/dev/null || fail "~/.acpx/config.json does not map omp to omp acp"
    [ -x "${HOME}/.local/bin/acpx" ] || fail "acpx is not installed in ~/.local/bin"
    cf_python -c 'import sys, yaml; s = yaml.safe_load(open(sys.argv[1]))["statusLine"]; assert s["leftSegments"][-1] == "status" and s["showHookStatus"] is False' \
        "${HOME}/.omp/agent/config.yml" || fail "~/.omp/agent/config.yml does not put extension statuses on the status line without a hooks line"
    [ -f "${HOME}/.omp/agent/extensions/aa-mode-icons.ts" ] || fail "the status icons omp extension is not installed"
    jq -e '.servers.marksman.disabled == true' "${HOME}/.omp/agent/lsp.json" >/dev/null || fail "~/.omp/agent/lsp.json does not disable marksman"
    # /tmp is a noexec tmpfs in host mode, so the stub omp must live under the home.
    mkdir -p "${HOME}/.cache"
    stub=$(mktemp -d "${HOME}/.cache/ponytail-stub.XXXXXX")
    trap 'rm -rf "${stub}"' EXIT
    mkdir -p "${stub}/bin" "${stub}/plugin/commands" "${stub}/plugin/skills/ponytail-review"
    printf 'prompt = "Review this diff."\n' >"${stub}/plugin/commands/ponytail-review.toml"
    printf 'Name what to cut.\n' >"${stub}/plugin/skills/ponytail-review/SKILL.md"
    printf '#!/bin/sh\ncat >/dev/null\nprintf "%%s\\n" "$STUB_OUT"\nexit "$STUB_RC"\n' >"${stub}/bin/omp"
    chmod +x "${stub}/bin/omp"
    for row in '0|0|Lean already. Ship.' '0|0|**Lean already. Ship.**' '0|0|`Lean already. Ship.`' '2|0|Cut the wrapper.' '1|1|Declined under the usage policy.' \
        $'2|0|L12: delete: dead flag. Nothing replaces it.\nLean already. Ship.' '2|0|net: -4 lines possible. The rest is lean already.'; do
        want=${row%%|*}; row=${row#*|}; omp_rc=${row%%|*}; omp_out=${row#*|}
        rc=0
        printf '+x\n' | STUB_OUT=${omp_out} STUB_RC=${omp_rc} PATH="${stub}/bin:${PATH}" PONYTAIL_PLUGIN_DIR="${stub}/plugin" \
            timeout 20 "${HOME}/.local/bin/ponytail-review" --stdin >/dev/null 2>&1 || rc=$?
        [ "${rc}" = "${want}" ] || fail "ponytail-review exited ${rc}, expected ${want}, when omp printed '${omp_out}' and exited ${omp_rc}"
    done
    rm -rf "${stub}"
    trap - EXIT
    for name in quota-axi:0.1.54 tasks-axi:0.2.6; do
        floor=${name#*:}; name=${name%%:*}
        version=$(resolved_version ".\"${name}\"")
        printf '%s\n%s\n' "${floor}" "${version}" | sort -C -V || fail "${name} ${version} is below the fleet floor ${floor}"
        printf '%s %s (floor %s)\n' "${name}" "${version}" "${floor}"
    done
    for name in ponytail i-have-adhd caveman; do
        jq -e --arg id "${name}@${name}" '.plugins[$id] | length > 0' "${HOME}/.omp/plugins/installed_plugins.json" >/dev/null \
            || fail "omp plugin ${name} is not installed"
    done
    printf 'gate agent omp (omp-as-pi or acp:omp), ponytail-review on omp, omp plugins installed\n'
}

container_mode() {
    SMOKE_TMP=$(mktemp -d -t crewship-smoke.XXXXXX)
    trap 'rm -rf "${SMOKE_TMP}"' EXIT

    printf '== Crewship container smoke (image role: %s)\n' "${CREWSHIP_IMAGE:-unknown}"
    printf '== %s %s\n\n' "$(uname -s)" "$(uname -m)"

    run_check identity                     check_identity
    run_check no-systemd                   check_no_systemd
    run_check no-host-surface              check_no_host_surface
    run_check profiles-disabled            check_profiles_disabled
    run_check source-checkout              check_source_checkout
    run_check workspace                    check_workspace
    run_check core-tools                   check_core_tools
    run_check resolved-releases            check_resolved_releases
    run_check herdr-install-layout         check_herdr_install_layout
    run_check herdr-unit                   check_herdr_unit
    run_check development-toolchain        check_development_toolchain
    run_check login-shell-environment      check_login_shell_environment
    run_check agent-gate                   check_agent_gate
    run_check no-baked-credentials         check_no_baked_credentials
    run_check herdr-config                 check_herdr_config
    run_check herdr-server-headless        check_herdr_server_headless
    run_check ship-inspect                 check_ship_inspect
    run_check ship-inspect-invalid         check_ship_inspect_rejects_invalid
    run_check ship-dock-no-overwrite       check_ship_dock_refuses_overwrite
    run_check installer-idempotent         check_installer_idempotent
    run_check rename-migration             check_rename_migration
    run_check ansible-second-pass          check_ansible_second_pass_idempotent

    printf '\n== %s/%s checks ran, %s failed\n' "${CHECKS_RUN}" "${CHECKS_TOTAL}" "${CHECKS_FAILED}"
    if [ "${CHECKS_FAILED}" -ne 0 ]; then
        printf '== failed:%s\n' "${FAILED_NAMES}"
        return 1
    fi
    return 0
}

case "${MODE}" in
    host) host_mode ;;
    container) container_mode ;;
    *) printf 'unreachable mode %s\n' "${MODE}" >&2; exit 2 ;;
esac
