# Job image of the Cloudflare container runner (docs/cloudflare-runner.md): the official
# GitHub Actions runner plus the apt packages the quick CI checks would otherwise install.
FROM ghcr.io/actions/actions-runner:latest
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      build-essential pkg-config clang cmake libssl-dev libzstd-dev libfontconfig-dev libfreetype-dev \
      libasound2-dev libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libx11-xcb-dev libxcb1-dev \
      libvulkan-dev mesa-vulkan-drivers xvfb git curl ca-certificates unzip \
 && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
USER runner
WORKDIR /home/runner
ENTRYPOINT ["/entrypoint.sh"]
