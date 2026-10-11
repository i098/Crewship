# Crewship container worker.
#
# This image is a repeatable, isolated, NON-ROOT worker and a provisioning smoke
# surface. It is deliberately NOT a native host:
#   * no systemd, no user manager, no `loginctl enable-linger`
#   * no SSH server, no Tailscale daemon, no XFCE/TigerVNC/noVNC desktop
#   * no host Docker socket, no host PID/network namespace, no credential binds
# Those live only on a real host provisioned by ansible/** with
# crewship.start_services=true. Inside this image the Crewship configuration sets
# start_services=false and disables the docker/tailscale/desktop profiles, so the
# playbook performs file/tool convergence only.
#
# Base image: ubuntu:latest, the newest Ubuntu LTS, pulled from mirror.gcr.io
# (Google's Docker Hub mirror: the same official image, no anonymous pull
# limit). Nothing is pinned; the registry's content digests verify the layers
# that are pulled.
#
# Build targets:
#   base    OS packages and the Crewship account only (no repository content)
#   worker  provisioned worker image; devcontainer and compose default
#   smoke   worker + tests/container-smoke.sh as CMD (behavior smoke)
#
# Distribution packages are intentionally not version-frozen: docs/security.md
# treats operating-system security updates as an OS responsibility rather than
# pinning a whole vulnerable package index. See docs/dependencies.md for tool
# release selection, download verification, and exceptions.

ARG UBUNTU_IMAGE=mirror.gcr.io/library/ubuntu:latest

FROM ${UBUNTU_IMAGE} AS base

ARG DEBIAN_FRONTEND=noninteractive
ARG CREWSHIP_USER=coder
ARG CREWSHIP_UID=1000
ARG CREWSHIP_GID=1000
ARG CREWSHIP_HOME=/home/coder
ARG CREWSHIP_WORKSPACE=/home/coder/Dev

# Prerequisites for: the uv bootstrap, ansible-core running against localhost
# (ansible.builtin.apt imports python3-apt from the system interpreter, so it is
# installed here instead of being auto-installed mid-playbook), the
# checksum-verifying tool installer (curl/ca-certificates/unzip/xz), the
# development profile (rustup toolchains need a C toolchain and pkg-config),
# and the behavior smoke script (procps/iproute2/jq).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        git \
        iproute2 \
        jq \
        less \
        libssl-dev \
        openssh-client \
        pkg-config \
        procps \
        python3 \
        python3-apt \
        python3-venv \
        sudo \
        tar \
        unzip \
        xz-utils \
        zstd; \
    rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships an "ubuntu" account on uid/gid 1000. Release the id before
# claiming it for the Crewship user so uid/gid stay configurable and stable.
RUN set -eux; \
    if getent passwd "${CREWSHIP_UID}" >/dev/null; then \
        existing_user="$(getent passwd "${CREWSHIP_UID}" | cut -d: -f1)"; \
        if [ "${existing_user}" != "${CREWSHIP_USER}" ]; then \
            userdel -r "${existing_user}" >/dev/null 2>&1 || userdel "${existing_user}"; \
        fi; \
    fi; \
    if getent group "${CREWSHIP_GID}" >/dev/null; then \
        existing_group="$(getent group "${CREWSHIP_GID}" | cut -d: -f1)"; \
        if [ "${existing_group}" != "${CREWSHIP_USER}" ]; then groupdel "${existing_group}"; fi; \
    fi; \
    if ! getent group "${CREWSHIP_USER}" >/dev/null; then \
        groupadd --gid "${CREWSHIP_GID}" "${CREWSHIP_USER}"; \
    fi; \
    if ! getent passwd "${CREWSHIP_USER}" >/dev/null; then \
        useradd --create-home --home-dir "${CREWSHIP_HOME}" \
                --uid "${CREWSHIP_UID}" --gid "${CREWSHIP_GID}" \
                --shell /bin/bash "${CREWSHIP_USER}"; \
    fi; \
    install -d -o "${CREWSHIP_USER}" -g "${CREWSHIP_USER}" -m 0755 \
        "${CREWSHIP_HOME}/.local" \
        "${CREWSHIP_HOME}/.local/bin" \
        "${CREWSHIP_HOME}/.local/share" \
        "${CREWSHIP_HOME}/.local/state" \
        "${CREWSHIP_HOME}/.config" \
        "${CREWSHIP_HOME}/.cache" \
        "${CREWSHIP_WORKSPACE}" \
        /opt/crewship; \
    # Ansible become for the unprivileged Crewship user. The container publishes no
    # ports by default, mounts no host socket and holds no host credentials, so the
    # blast radius of this sudoers entry is the container itself. A real host keeps
    # its own sudo policy; this file is never applied by ansible/**.
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${CREWSHIP_USER}" > /etc/sudoers.d/90-crewship; \
    chmod 0440 /etc/sudoers.d/90-crewship; \
    visudo -cf /etc/sudoers.d/90-crewship

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    CREWSHIP_USER=${CREWSHIP_USER} \
    CREWSHIP_HOME=${CREWSHIP_HOME} \
    HOME=${CREWSHIP_HOME} \
    CREWSHIP_WORKSPACE=${CREWSHIP_WORKSPACE} \
    CREWSHIP_ROOT=/opt/crewship \
    PATH=${CREWSHIP_HOME}/.local/bin:${CREWSHIP_HOME}/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---------------------------------------------------------------------------
# worker: provisioned image built through the repository's own CLI interfaces.
# ---------------------------------------------------------------------------
FROM base AS worker

ARG CREWSHIP_USER=coder
ARG CREWSHIP_HOME=/home/coder
ARG CREWSHIP_WORKSPACE=/home/coder/Dev
ARG CREWSHIP_CONFIG_FILE=containers/crewship.container.yml

COPY --chown=${CREWSHIP_USER}:${CREWSHIP_USER} . /opt/crewship

RUN set -eux; \
    printf 'role=worker\nsource=/opt/crewship\nuser=%s\nhome=%s\nworkspace=%s\nconfig=%s\nsystemd=absent\ntailscale=absent\ndesktop=absent\n' \
        "${CREWSHIP_USER}" "${CREWSHIP_HOME}" "${CREWSHIP_WORKSPACE}" "${CREWSHIP_CONFIG_FILE}" \
        > /etc/crewship-image; \
    chmod 0444 /etc/crewship-image

USER ${CREWSHIP_USER}
WORKDIR /opt/crewship

# Executable bits are part of the interface: ./onboard.sh, ./ship.sh and the
# smoke script are invoked directly, including from a context that lost them.
RUN set -eux; chmod +x onboard.sh ship.sh tests/container-smoke.sh

# Latest uv bootstrap + locked Python dependencies (no provisioning yet). The
# one uv lookup takes the same optional `github_token` secret as `launch`.
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    set -eux; ./onboard.sh

# Schema validation through the repository's own validator.
RUN set -eux; ./ship.sh inspect --config "${CREWSHIP_CONFIG_FILE}"

# A valid document is not automatically the right document: this guard parses it
# and compares it with the live image account, then refuses any capability an
# ordinary container cannot host.
RUN set -eux; uv run --project . --locked python containers/assert-image-config.py "${CREWSHIP_CONFIG_FILE}"

# The real convergence run. `launch` installs the latest, checksum-verified
# agent and development toolchain (the three omp marketplace plugins are the one
# unverified exception) through scripts/provisions.py and renders
# the user-scope files; start_services=false keeps it off systemd and linger.
# The optional `github_token` BuildKit secret authenticates the latest-release
# lookups (shared CI runner IPs exhaust the unauthenticated API budget). It is
# exposed to the lookup steps only (onboard.sh and this one), never as an ARG,
# ENV, layer file or history entry; without it the lookup runs unauthenticated.
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    set -eux; ./ship.sh launch --config "${CREWSHIP_CONFIG_FILE}"

ENV CREWSHIP_IMAGE=worker \
    CREWSHIP_CONFIG=/opt/crewship/${CREWSHIP_CONFIG_FILE}

LABEL org.opencontainers.image.title="crewship-worker" \
      org.opencontainers.image.description="Isolated non-root Crewship worker; no systemd, Tailscale or desktop." \
      org.opencontainers.image.source="https://github.com/i098/Crewship" \
      org.opencontainers.image.licenses="FSL-1.1-ALv2" \
      org.opencontainers.image.base.name="mirror.gcr.io/library/ubuntu:latest"

WORKDIR ${CREWSHIP_WORKSPACE}
CMD ["/bin/bash"]

# ---------------------------------------------------------------------------
# smoke: identical filesystem, runs the behavior smoke as its default command.
# ---------------------------------------------------------------------------
FROM worker AS smoke

ENV CREWSHIP_IMAGE=smoke

LABEL org.opencontainers.image.title="crewship-smoke" \
      org.opencontainers.image.description="Crewship worker image running tests/container-smoke.sh."

WORKDIR /opt/crewship
CMD ["/opt/crewship/tests/container-smoke.sh", "--in-container"]
