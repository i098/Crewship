FROM ghcr.io/actions/actions-runner:latest
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN rm -f /etc/apt/apt.conf.d/docker-clean
ARG REFRESH
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      build-essential pkg-config libgtk-3-0 unzip git curl ca-certificates gnupg lsb-release postgresql-common \
      clang cmake libssl-dev libzstd-dev libfontconfig-dev libfreetype-dev libasound2-dev \
      libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libx11-xcb-dev libxcb1-dev libvulkan-dev mesa-vulkan-drivers \
 && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
 && apt-get install -y -qq --no-install-recommends postgresql-17 postgresql-client-17 postgresql-18 postgresql-client-18 postgresql-18-pgvector \
 && curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash \
 && tag=$(basename "$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/mozilla/sccache/releases/latest)") \
 && asset=sccache-$tag-$(uname -m)-unknown-linux-musl.tar.gz \
 && curl -fsSL -o /tmp/$asset https://github.com/mozilla/sccache/releases/download/$tag/$asset \
 && echo "$(curl -fsSL https://github.com/mozilla/sccache/releases/download/$tag/$asset.sha256)  /tmp/$asset" | sha256sum -c - \
 && tar -xzf /tmp/$asset -C /tmp \
 && install -m 755 /tmp/sccache-$tag-*/sccache /usr/local/bin/sccache \
 && rm -rf /tmp/sccache-* \
 && install -d -o runner -g runner /home/runner/.cargo /home/runner/.cache
# Jobs mount their own directory over /var/lib/postgresql (see CONTAINER_PREP), so the
# clusters that the packages created are kept here and copied in when a job starts.
# Only the newest installed package creates its main cluster, so create the 17 one when it is
# missing. Each cluster starts on port 5432, so stop both and start neither at boot: a job
# starts the version it needs (see docs/ci-pool.md).
RUN [ -d /etc/postgresql/17/main ] || (pg_createcluster 17 main && pg_conftool 17 main set port 5432)  && for v in 17 18; do pg_ctlcluster $v main stop 2>/dev/null || true; echo manual > /etc/postgresql/$v/main/start.conf; done  && cp -a /var/lib/postgresql /opt/postgresql-seed
# The compose plugin, for repositories whose jobs talk to their own daemon (DIND_IMAGE).
COPY --from=docker:dind-rootless /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/
USER runner
