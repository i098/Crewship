ARG BASE_IMAGE
FROM docker:29-dind@sha256:4bbc7223f81db790097c6dea42fb93e05b8fead4f0431fbe6ccaba6e8473201c AS engine
FROM ${BASE_IMAGE}
USER root
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables && rm -rf /var/lib/apt/lists/*
COPY --from=engine /usr/local/bin/containerd* /usr/local/bin/docker /usr/local/bin/docker-init /usr/local/bin/docker-proxy /usr/local/bin/dockerd /usr/local/bin/runc /usr/local/bin/
COPY --from=engine /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/
RUN mv /home/runner/run.sh /home/runner/run-original.sh
COPY --chmod=755 <<'EOF' /home/runner/run.sh
#!/bin/sh
set -eu
log=$(mktemp)
# Sysbox confines the daemon and all its containers inside this job's cgroup.
sudo -n /usr/local/bin/dockerd --host=unix:///var/run/docker.sock --group=runner --storage-driver=overlay2 >"$log" 2>&1 </dev/null &
daemon=$!
for i in $(seq 60); do
  if docker info >/dev/null 2>&1; then
    if [ "${1-}" = --check-dind-runtime ]; then exit 0; fi
    exec /home/runner/run-original.sh "$@"
  fi
  kill -0 "$daemon" 2>/dev/null || break
  sleep 1
done
cat "$log" >&2
echo 'runner-up: Docker did not start' >&2
exit 125
EOF
USER runner
