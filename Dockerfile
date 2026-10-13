# Crewship container worker.
#
# This image is a repeatable, isolated, NON-ROOT worker and a provisioning smoke
# surface. It is deliberately NOT a native host:
#   * no systemd, no user manager, no `loginctl enable-linger`
#   * no SSH server, no Tailscale daemon, no XFCE/TigerVNC/noVNC desktop
#   * no host Docker socket, no host PID/network namespace, no credential binds
# Those live only on a real host provisioned by blueprint/ansible/** with
# crewship.start_services=true. Inside this image the Crewship configuration sets
# start_services=false and disables the docker/tailscale/desktop profiles, so the
# playbook performs file/tool convergence only.
#
# Base image: ubuntu:latest, the newest Ubuntu LTS, pulled from mirror.gcr.io
# (Google's Docker Hub mirror: the same official image, no anonymous pull
# limit). Nothing is pinned; the registry's content digests verify the layers
# that are pulled.
#
# Size, one line per step (3.7 GB -> 2.88 GB uncompressed; 1.21 GB -> 0.99 GB
# compressed):
#   1. Slim base: measured, NOT applied. ubuntu 113 MB, debian:stable-slim
#      86 MB, alpine 9 MB. Effect 0 MB: the playbook preflight requires Ubuntu,
#      and alpine (musl) breaks the glibc builds of node, bun and omp addons.
#   2. Multi-stage: applied. `builder` provisions and cleans up; `worker` is
#      separate. Compilers stay (rustc links with cc, the playbook installs
#      build-essential). 0 MB alone; it makes step 5 possible.
#   3. Manifests before source: applied. pyproject.toml, uv.lock, onboard.sh and
#      scripts/provisions.py are copied before `COPY .`; the Dockerfile is kept
#      out of the context. Size 0. After a README edit the onboard layer is
#      cached; after a Dockerfile-only edit every builder layer is cached,
#      including launch.
#   4. Lockfile installs: applied where a lockfile exists. Python uses
#      `uv sync --locked`. The npm-registry tools are installed with
#      `bun add -g --exact` at the resolved version. A global install has no
#      project lockfile, so `bun install --frozen-lockfile` and `npm ci` have
#      nothing to apply to. 0 MB.
#   5. Final stage copies only built output: applied. `FROM scratch` +
#      `COPY --from=builder / /`. 3.7 GB -> 2.88 GB uncompressed, 1.21 GB ->
#      0.99 GB compressed. The same builder without this step is 2.25 GB
#      compressed.
#   6. Tight .dockerignore: applied. Context is 2.3 MB in 267 files; Dockerfile,
#      CHANGELOG.md, CONTRIBUTING.md, SETUP.md and install.sh are excluded.
#      About -70 KB.
#
# Build targets:
#   base     OS packages and the Crewship account only (no repository content)
#   builder  base + the provisioning run, its caches and its build-only files
#   worker   the builder's filesystem without them, as one layer; devcontainer
#            and compose default
#   smoke    worker + tests/container-smoke.sh as CMD (behavior smoke)
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
    # its own sudo policy; this file is never applied by blueprint/ansible/**.
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
    PATH=${CREWSHIP_HOME}/.local/bin:${CREWSHIP_HOME}/.bun/bin:${CREWSHIP_HOME}/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---------------------------------------------------------------------------
# builder: provisioned through the repository's own CLI interfaces.
# ---------------------------------------------------------------------------
FROM base AS builder

ARG CREWSHIP_USER=coder
ARG CREWSHIP_HOME=/home/coder
ARG CREWSHIP_WORKSPACE=/home/coder/Dev
ARG CREWSHIP_CONFIG_FILE=blueprint/containers/crewship.container.yml

RUN set -eux; \
    printf 'role=worker\nsource=/opt/crewship\nuser=%s\nhome=%s\nworkspace=%s\nconfig=%s\nsystemd=absent\ntailscale=absent\ndesktop=absent\n' \
        "${CREWSHIP_USER}" "${CREWSHIP_HOME}" "${CREWSHIP_WORKSPACE}" "${CREWSHIP_CONFIG_FILE}" \
        > /etc/crewship-image; \
    chmod 0444 /etc/crewship-image

USER ${CREWSHIP_USER}
WORKDIR /opt/crewship

# Manifests before source: the locked Python environment depends only on these
# files, so a change elsewhere in the repository reuses this layer. Latest uv
# bootstrap + locked Python dependencies (no provisioning yet). The one uv
# lookup takes the same optional `github_token` secret as `launch`.
COPY --chown=${CREWSHIP_USER}:${CREWSHIP_USER} pyproject.toml uv.lock onboard.sh /opt/crewship/
COPY --chown=${CREWSHIP_USER}:${CREWSHIP_USER} scripts/provisions.py /opt/crewship/scripts/
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    set -eux; bash ./onboard.sh

COPY --chown=${CREWSHIP_USER}:${CREWSHIP_USER} . /opt/crewship

# Executable bits are part of the interface: ./onboard.sh, ./ship.sh and the
# smoke script are invoked directly, including from a context that lost them.
RUN set -eux; chmod +x onboard.sh ship.sh tests/container-smoke.sh

# Schema validation through the repository's own validator.
RUN set -eux; ./ship.sh inspect --config "${CREWSHIP_CONFIG_FILE}"

# A valid document is not automatically the right document: this guard parses it
# and compares it with the live image account, then refuses any capability an
# ordinary container cannot host.
RUN set -eux; uv run --project . --locked python blueprint/containers/assert-image-config.py "${CREWSHIP_CONFIG_FILE}"

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

# Size: files no worker process reads. The worker stage copies the filesystem
# without the layers, so what is deleted here is gone from the image.
#   * package-manager caches, the apt indexes (the next apply refreshes them),
#     rustup docs, and node's C headers (node-gyp downloads its own)
#   * in each npm tool prefix: source maps, and TypeScript declarations outside
#     omp's own packages
#   * in omp: onnxruntime-web (only the browser build of transformers.js loads
#     it; the Node build loads onnxruntime-node), the AVX2 build of pi-natives
#     (its loader falls back to the baseline build, which runs on every x86-64
#     CPU), onnxruntime-node binaries for other platforms, and the CUDA/TensorRT
#     providers (a container with no GPU runs the CPU provider)
#   * Mesa's GPU driver and its LLVM (libgbm1, which chrome-headless-shell links,
#     depends on them, but libgbm loads the driver only to open a GPU device;
#     the shell renders with its own bundled SwiftShader).
#     `sudo apt-get install --reinstall mesa-libgallium libllvm21` restores them
#   * symbol tables in the rustup toolchain and the npm tools' native addons.
#     The release binaries under tools/ keep their bytes: the installer checks
#     their SHA-256 again on every run
RUN set -eux; \
    share="${CREWSHIP_HOME}/.local/share/crewship"; \
    sudo rm -rf /var/lib/apt/lists/* /usr/lib/*/libLLVM*.so* /usr/lib/*/libgallium-*.so \
        /usr/lib/*/dri/*_drv_video.so /usr/lib/*/gbm/dri_gbm.so; \
    rm -rf "${CREWSHIP_HOME}/.npm" "${CREWSHIP_HOME}/.cache/uv" \
        "${CREWSHIP_HOME}/.bun/install/cache" "${CREWSHIP_HOME}/.cache/pip" \
        "${CREWSHIP_HOME}/.cargo/registry" "${CREWSHIP_HOME}/.cargo/git" \
        "${CREWSHIP_HOME}"/.rustup/toolchains/*/share/doc \
        "${share}"/tools/node/*/*/*/include \
        "${share}"/omp/*/node_modules/onnxruntime-web \
        "${share}"/omp/*/node_modules/@oh-my-pi/pi-natives-*/pi_natives.*-modern.node; \
    find "${share}"/*/[0-9]*/node_modules -type f \( -name '*.map' -o \
        \( \( -name '*.d.ts' -o -name '*.d.mts' -o -name '*.d.cts' \) ! -path '*/@oh-my-pi/*' \) \) -delete; \
    case "$(uname -m)" in x86_64) arch=x64 ;; aarch64) arch=arm64 ;; *) arch= ;; esac; \
    if [ -n "${arch}" ]; then \
        find "${share}" -type d -path '*/onnxruntime-node/bin/napi-v*' -prune -print | \
        while read -r dir; do \
            find "${dir}" -mindepth 1 -maxdepth 1 ! -name linux -exec rm -rf {} +; \
            find "${dir}/linux" -mindepth 1 -maxdepth 1 ! -name "${arch}" -exec rm -rf {} + 2>/dev/null || true; \
        done; \
    fi; \
    find "${share}" -path '*/onnxruntime-node/bin/*' \
        \( -name 'libonnxruntime_providers_cuda.so*' -o -name 'libonnxruntime_providers_tensorrt.so*' \) -delete; \
    find "${CREWSHIP_HOME}"/.rustup/toolchains "${share}"/*/[0-9]*/node_modules -type f \
        \( -name '*.so' -o -name '*.so.*' -o -name '*.node' -o -perm -u+x \) \
        ! -path '*/lib/rustlib/*/lib/*' -print | \
    while read -r file; do \
        if [ "$(head -c 4 "${file}" | tail -c 3)" = ELF ]; then \
            strip --strip-unneeded "${file}" || true; \
        fi; \
    done

# ---------------------------------------------------------------------------
# worker: the builder's final filesystem as one layer. A file a later builder
# step changed or deleted is stored once or not at all, instead of once per
# layer. FROM scratch inherits no configuration, so the base ENV is restated.
# ---------------------------------------------------------------------------
FROM scratch AS worker

ARG CREWSHIP_USER=coder
ARG CREWSHIP_HOME=/home/coder
ARG CREWSHIP_WORKSPACE=/home/coder/Dev
ARG CREWSHIP_CONFIG_FILE=blueprint/containers/crewship.container.yml

COPY --from=builder / /

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    CREWSHIP_USER=${CREWSHIP_USER} \
    CREWSHIP_HOME=${CREWSHIP_HOME} \
    HOME=${CREWSHIP_HOME} \
    CREWSHIP_WORKSPACE=${CREWSHIP_WORKSPACE} \
    CREWSHIP_ROOT=/opt/crewship \
    PATH=${CREWSHIP_HOME}/.local/bin:${CREWSHIP_HOME}/.bun/bin:${CREWSHIP_HOME}/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

USER ${CREWSHIP_USER}

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
