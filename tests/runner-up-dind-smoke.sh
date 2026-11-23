#!/bin/sh
set -eu

work=$(mktemp -d)
cd "$work"
trap 'docker compose down --volumes >/dev/null 2>&1 || :; rm -rf "$work"' EXIT

docker info --format 'daemon={{.ID}} cgroup={{.CgroupDriver}}'
test -z "$(docker ps -aq)"
docker buildx inspect --bootstrap

cat > compose.yml <<'EOF'
services:
  check:
    build: .
EOF
cat > Dockerfile <<'EOF'
FROM alpine:3.23
COPY expected /expected
CMD ["grep", "-x", "runner-up-dind-ok", "/expected"]
EOF
printf '%s\n' runner-up-dind-ok > expected
docker compose up --build --abort-on-container-exit --exit-code-from check
